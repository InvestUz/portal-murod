import hashlib
import io
import json
import tarfile

import pytest

from scripts import prepare_build_tools as tools


URL='https://registry.npmjs.org/npm/-/npm-12.2.1.tgz'


def archive(extra=()):
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz') as bundle:
        payload=json.dumps({'name':'npm','version':'12.2.1'}).encode()
        member=tarfile.TarInfo('package/package.json');member.size=len(payload)
        bundle.addfile(member,io.BytesIO(payload))
        for name,kind in extra:
            member=tarfile.TarInfo(name);member.type=kind
            if kind==tarfile.SYMTYPE:member.linkname='../../outside'
            bundle.addfile(member,io.BytesIO())
    return stream.getvalue()


def response(monkeypatch,data,url=URL):
    class Response(io.BytesIO):
        def geturl(self):return url
    monkeypatch.setattr(tools,'urlopen',lambda *args,**kwargs:Response(data))
    return {'version':'12.2.1','url':URL,'sha512':hashlib.sha512(data).hexdigest()}


def test_installs_only_authenticated_package_identity(tmp_path,monkeypatch):
    spec=response(monkeypatch,archive())
    tools.install_package('npm',spec,tmp_path)
    assert json.loads((tmp_path/'npm/package.json').read_text())['version']=='12.2.1'
    assert sorted(p.name for p in tmp_path.iterdir())==['npm']


def test_hash_mismatch_does_not_install(tmp_path,monkeypatch):
    spec=response(monkeypatch,archive());spec['sha512']='0'*128
    with pytest.raises(ValueError,match='integrity'):tools.install_package('npm',spec,tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('members',[
    [('package/../../outside',tarfile.REGTYPE)],
    [('package/link',tarfile.SYMTYPE)],
    [('package/package.json',tarfile.REGTYPE)],
    [('/package/outside',tarfile.REGTYPE)],
    [('package/device',tarfile.CHRTYPE)],
])
def test_unsafe_archive_never_becomes_installed_tree(tmp_path,monkeypatch,members):
    spec=response(monkeypatch,archive(members))
    with pytest.raises(ValueError):tools.install_package('npm',spec,tmp_path)
    assert not list(tmp_path.iterdir())


def test_redirect_and_expanded_limit_refuse_installation(tmp_path,monkeypatch):
    data=archive();spec=response(monkeypatch,data,'https://unexpected.invalid/npm.tgz')
    with pytest.raises(ValueError,match='redirect'):tools.install_package('npm',spec,tmp_path)
    spec=response(monkeypatch,data);monkeypatch.setattr(tools,'MAX_EXPANDED',1)
    with pytest.raises(ValueError,match='limit'):tools.install_package('npm',spec,tmp_path)
    assert not list(tmp_path.iterdir())
