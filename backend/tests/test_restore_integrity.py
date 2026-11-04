"""Real cryptographic/archive regressions; no PostgreSQL or Docker emulation."""
import io
import os
import tarfile
from pathlib import Path
import pytest
from operations.crypto_stream import encrypt, decrypt, CHUNK
from operations.volume_archive import pack, unpack, STAGE_PREFIX


@pytest.mark.parametrize('damage', ['tag', 'ciphertext', 'truncate', 'wrong-key'])
def test_invalid_encrypted_backup_never_exposes_plaintext(damage):
    key = os.urandom(32)
    encrypted = io.BytesIO()
    encrypt(io.BytesIO(b'private content'*(CHUNK//7)), encrypted, key)
    value = bytearray(encrypted.getvalue())
    if damage == 'tag':
        value[-1] ^= 1
    elif damage == 'ciphertext':
        value[len(value)//2] ^= 1
    elif damage == 'truncate':
        value = value[:-1]
    else:
        key = os.urandom(32)
    output = io.BytesIO()
    with pytest.raises(Exception):
        decrypt(io.BytesIO(value), output, key)
    assert output.getvalue() == b''


def test_encrypted_restore_stages_ciphertext_only_and_preserves_legacy_format(tmp_path, monkeypatch):
    import operations.crypto_stream as crypto
    original = crypto.tempfile.TemporaryFile
    staged = []
    def temporary(*args, **kwargs):
        value = original(*args, dir=tmp_path, **kwargs)
        staged.append(value)
        return value
    monkeypatch.setattr(crypto.tempfile, 'TemporaryFile', temporary)
    key = os.urandom(32)
    content = b'confidential original bytes'*100000
    source = io.BytesIO()
    encrypt(io.BytesIO(content), source, key)
    original_bytes = source.getvalue()
    class ObservedOutput(io.BytesIO):
        def write(self, data):
            position = staged[0].tell()
            staged[0].seek(0)
            assert staged[0].read() == original_bytes
            staged[0].seek(position)
            return super().write(data)
    result = ObservedOutput()
    decrypt(io.BytesIO(original_bytes), result, key)
    assert result.getvalue() == content
    assert original_bytes.startswith(b'TIPB1')
    assert staged[0].closed and not list(tmp_path.iterdir())


def test_bad_archive_does_not_erase_existing_files_even_after_valid_first_entry(tmp_path):
    root = tmp_path/'files'
    root.mkdir()
    (root/'old.pdf').write_bytes(b'old verified document')
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        first = tarfile.TarInfo('new.pdf')
        first.size = 3
        tar.addfile(first, io.BytesIO(b'new'))
        invalid = tarfile.TarInfo('../escape')
        invalid.size = 3
        tar.addfile(invalid, io.BytesIO(b'bad'))
    with pytest.raises(ValueError):
        unpack(io.BytesIO(archive.getvalue()), root, clear=True)
    assert {path.name for path in root.iterdir()} == {'old.pdf'}
    assert (root/'old.pdf').read_bytes() == b'old verified document'
    assert not (tmp_path/'escape').exists()


def test_truncated_archive_does_not_erase_existing_files(tmp_path):
    root = tmp_path/'files'
    root.mkdir()
    (root/'old').write_bytes(b'preserved')
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w') as tar:
        member = tarfile.TarInfo('incoming')
        member.size = 10000
        tar.addfile(member, io.BytesIO(b'x'*10000))
    with pytest.raises(ValueError):
        unpack(io.BytesIO(archive.getvalue()[:2000]), root, clear=True)
    assert list(path.name for path in root.iterdir()) == ['old']
    assert (root/'old').read_bytes() == b'preserved'


def test_replacement_rolls_back_old_tree_if_commit_move_fails(tmp_path, monkeypatch):
    source, root = tmp_path/'source', tmp_path/'files'
    source.mkdir()
    root.mkdir()
    (source/'new-a').write_bytes(b'a')
    (source/'new-b').write_bytes(b'b')
    (root/'old').write_bytes(b'old')
    archive = io.BytesIO()
    pack(source, archive)
    real_replace = os.replace
    def failing_replace(source, target):
        if Path(source).parent.name == 'incoming' and Path(source).name == 'new-b':
            raise OSError('Injected disk failure during commit')
        return real_replace(source, target)
    monkeypatch.setattr('operations.volume_archive.os.replace', failing_replace)
    with pytest.raises(OSError, match='Injected'):
        unpack(io.BytesIO(archive.getvalue()), root, clear=True)
    assert (root/'old').read_bytes() == b'old'
    assert list(path.name for path in root.iterdir()) == ['old']


def test_successful_staged_restore_replaces_files_and_removes_stage(tmp_path):
    source, root = tmp_path/'source', tmp_path/'files'
    source.mkdir()
    root.mkdir()
    (source/'document').write_bytes(b'new content')
    (root/'old').write_bytes(b'old content')
    archive = io.BytesIO()
    pack(source, archive)
    unpack(io.BytesIO(archive.getvalue()), root, clear=True)
    assert list(path.name for path in root.iterdir()) == ['document']
    assert (root/'document').read_bytes() == b'new content'


def test_interrupted_restore_is_never_silently_packed_or_erased(tmp_path):
    root = tmp_path/'files'
    (root/(STAGE_PREFIX+'interrupted')/'previous').mkdir(parents=True)
    (root/(STAGE_PREFIX+'interrupted')/'previous'/'document').write_bytes(b'keep recovery data')
    with pytest.raises(ValueError, match='Unfinished'):
        pack(root, io.BytesIO())
    with pytest.raises(ValueError, match='Unfinished'):
        unpack(io.BytesIO(), root, clear=True)
    assert (root/(STAGE_PREFIX+'interrupted')/'previous'/'document').read_bytes() == b'keep recovery data'


def test_failed_rollback_preserves_recovery_tree_and_blocks_future_backup(tmp_path, monkeypatch):
    source, root = tmp_path/'source', tmp_path/'files'
    source.mkdir()
    root.mkdir()
    (source/'new').write_bytes(b'new')
    (root/'old').write_bytes(b'old verified bytes')
    archive = io.BytesIO()
    pack(source, archive)
    real_replace = os.replace
    def failing_replace(source, target):
        if Path(source).parent.name in {'incoming', 'previous'}:
            raise OSError('Injected commit and rollback failure')
        return real_replace(source, target)
    monkeypatch.setattr('operations.volume_archive.os.replace', failing_replace)
    with pytest.raises(ValueError, match='rollback failed'):
        unpack(io.BytesIO(archive.getvalue()), root, clear=True)
    stages = list(root.glob(STAGE_PREFIX+'*'))
    assert len(stages) == 1
    assert (stages[0]/'previous'/'old').read_bytes() == b'old verified bytes'
    with pytest.raises(ValueError, match='Unfinished'):
        pack(root, io.BytesIO())


@pytest.mark.parametrize('resume', [True, False])
def test_real_encrypted_snapshot_can_keep_services_stopped_for_restore(tmp_path, monkeypatch, resume):
    import json
    import sys
    from operations import backup
    from operations.crypto_stream import encrypt
    calls = []
    key = os.urandom(32)
    class Controller:
        directory = tmp_path/'configuration'
        environment = {'PORTAL_RELEASE': 'test-release'}
        process_environment = {}
        def backup_key(self):return key
        def run(self, *args, **kwargs):calls.append(args)
        def recover(self):calls.append(('recover',))
        def command(self, *args):return list(args)
        def codec(self, mode):return [sys.executable, str(Path(__file__).resolve().parents[2]/'operations/crypto_stream.py'), mode]
        def source_commit(self):return 'test-source'
    def encrypted_source(source_command, codec_command, destination, key, environment):
        with open(destination, 'wb') as stream:
            encrypt(io.BytesIO(b'synthetic database or archive stream'), stream, key)
    monkeypatch.setattr(backup, 'encrypt_command', encrypted_source)
    snapshot = backup.make_backup(Controller(), tmp_path/'backups', resume_services=resume)
    assert backup.authenticate(snapshot, key)['release'] == 'test-release'
    assert json.loads((snapshot/'manifest.json').read_text())['format'] == 1
    assert calls[:2] == [('stop', 'proxy', 'worker', 'app'), ('recover',)]
    assert any(call[0] == 'up' for call in calls) == resume
    assert (Controller.directory/'last-backup.json').exists()


def test_restore_scratch_is_private_tool_storage_not_application_storage():
    import yaml
    root = Path(__file__).resolve().parents[2]
    compose = yaml.safe_load((root/'compose.yaml').read_text())
    assert compose['volumes']['backup-work']['labels']
    for name, service in compose['services'].items():
        mounts = service.get('volumes', [])
        scratch = any(mount.startswith('backup-work:') for mount in mounts)
        assert scratch == (name in {'backup-tool', 'restore-tool'})
        if scratch:
            assert service['environment']['TMPDIR'] == '/var/lib/portal/backup-work'
            assert service['network_mode'] == 'none'
            assert service['logging']['driver'] == 'none'


@pytest.mark.parametrize('target', ['http://example.invalid/tool', 'file:///etc/passwd', 'ftp://example.invalid/tool'])
def test_scanner_download_rejects_https_downgrade_or_local_redirect(target):
    from urllib.request import Request
    from operations.install_trivy import HTTPSOnlyRedirect
    with pytest.raises(ValueError, match='HTTPS'):
        HTTPSOnlyRedirect().redirect_request(Request('https://github.com/official/tool'), None, 302, 'Found', {}, target)
