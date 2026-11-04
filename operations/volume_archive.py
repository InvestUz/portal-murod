"""Restore regular private files through a staged tree with rollback on failure."""
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path('/var/lib/portal/files')
STAGE_PREFIX = '.portal-restore-'


def pack(source, destination):
    source = Path(source)
    if any(path.name.startswith(STAGE_PREFIX) for path in source.iterdir()):
        raise ValueError('Unfinished restoration must be recovered before backup')
    with tarfile.open(fileobj=destination, mode='w|') as archive:
        for path in sorted(source.rglob('*')):
            if path.is_symlink():
                raise ValueError('Symlink in private storage')
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(source)), recursive=False)


def extract(source, root):
    names = set()
    with tarfile.open(fileobj=source, mode='r|') as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if (name.is_absolute() or '..' in name.parts or '\\' in member.name
                    or ':' in member.name or str(name) in names
                    or (name.parts and name.parts[0].startswith(STAGE_PREFIX))):
                raise ValueError('Unsafe or duplicate backup path')
            names.add(str(name))
            if member.type not in {tarfile.REGTYPE, tarfile.AREGTYPE, tarfile.DIRTYPE} or member.sparse or member.size < 0:
                raise ValueError('Only ordinary files and directories may be restored')
            target = root.joinpath(*name.parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError('Backup path escapes its volume')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                continue
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError('Missing file data')
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'wb') as destination:
                shutil.copyfileobj(stream, destination, 1024*1024)


def remove(path):
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def unpack(source, root, clear=False):
    root = Path(root).resolve()
    if root == Path('/'):
        raise ValueError('Invalid restore root')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    existing = list(root.iterdir())
    if any(path.name.startswith(STAGE_PREFIX) for path in existing):
        raise ValueError('Unfinished restoration requires operator recovery')
    if not clear and existing:
        raise ValueError('Restore destination must be empty')
    stage = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=root))
    incoming, previous = stage/'incoming', stage/'previous'
    incoming.mkdir(mode=0o700)
    previous.mkdir(mode=0o700)
    preserve_stage = False
    try:
        # No live file is touched before every archive member has been read.
        extract(source, incoming)
        moved_new = []
        try:
            for old in existing:
                os.replace(old, previous/old.name)
            for new in list(incoming.iterdir()):
                os.replace(new, root/new.name)
                moved_new.append(root/new.name)
        except BaseException:
            try:
                for new in moved_new:
                    remove(new)
                for old in list(previous.iterdir()):
                    os.replace(old, root/old.name)
            except BaseException as error:
                preserve_stage = True
                raise ValueError('Restore rollback failed; preserve the private staging directory for recovery') from error
            raise
    except (tarfile.TarError, EOFError) as error:
        raise ValueError('Invalid or truncated backup archive') from error
    finally:
        if not preserve_stage:
            shutil.rmtree(stage)


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'pack':
            pack(ROOT, sys.stdout.buffer)
        elif sys.argv[1] == 'unpack':
            unpack(sys.stdin.buffer, ROOT, clear='--replace' in sys.argv)
        else:
            raise ValueError('Unknown archive operation')
    except Exception:
        print('Private file archive operation failed; retain the pre-restore backup.', file=sys.stderr)
        raise SystemExit(1)
