"""Synthetic archive boundary tests; the official executable is checked by actual builds."""
import hashlib
import io
import tarfile

import pytest

from scripts import prepare_node as node


def fixture(monkeypatch,entries=None,binary=None):
    header=bytearray(64);header[:6]=b'\x7fELF\x02\x01';header[18:20]=(62).to_bytes(2,'little')
    binary=binary if binary is not None else bytes(header)+b'synthetic executable bytes'
    prefix='node-v24.22.2-linux-x64-musl';stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:xz') as archive:
        for name,data,link in entries or [(prefix+'/bin/node',binary,None),(prefix+'/LICENSE',b'Synthetic test license',None)]:
            member=tarfile.TarInfo(name)
            if link:member.type=tarfile.SYMTYPE;member.linkname=link;archive.addfile(member)
            else:member.size=len(data);archive.addfile(member,io.BytesIO(data))
    data=stream.getvalue()
    monkeypatch.setattr(node,'open_https',lambda *args,**kwargs:io.BytesIO(data))
    spec={'format':1,'version':'24.22.2','platform':'linux-x64-musl','url':'https://nodejs.org/dist/v24.22.2/'+prefix+'.tar.xz','sha256':hashlib.sha256(data).hexdigest(),'binarySha256':hashlib.sha256(binary).hexdigest()}
    return spec,binary,prefix


def test_installs_only_executable_and_license(monkeypatch,tmp_path):
    spec,binary,_=fixture(monkeypatch)
    destination=tmp_path/'node';node.install_node(spec,destination)
    assert sorted(p.name for p in destination.iterdir())==['LICENSE','node']
    assert (destination/'node').read_bytes()==binary
    with pytest.raises(ValueError,match='already exists'):node.install_node(spec,destination)


@pytest.mark.parametrize('failure',['archive-hash','binary-hash','architecture','size','expansion','wrong-version'])
def test_bad_artifact_is_not_published(monkeypatch,tmp_path,failure):
    spec,_,_=fixture(monkeypatch,binary=b'invalid-ELF' if failure=='architecture' else None)
    if failure=='archive-hash':spec['sha256']='0'*64
    if failure=='binary-hash':spec['binarySha256']='0'*64
    if failure=='size':monkeypatch.setattr(node,'MAX_ARCHIVE',1)
    if failure=='expansion':monkeypatch.setattr(node,'MAX_EXPANSION',1)
    if failure=='wrong-version':spec['version']='26.0.0'
    with pytest.raises(ValueError):node.install_node(spec,tmp_path/'node')
    assert not (tmp_path/'node').exists()


@pytest.mark.parametrize('case',['link','duplicate','missing'])
def test_selected_archive_member_must_be_unique_regular_file(monkeypatch,tmp_path,case):
    _,binary,prefix=fixture(monkeypatch)
    entries=[(prefix+'/LICENSE',b'Synthetic test license',None)]
    if case=='link':entries.append((prefix+'/bin/node',b'', '../../outside'))
    if case=='duplicate':entries.extend([(prefix+'/bin/node',binary,None)]*2)
    spec,_,_=fixture(monkeypatch,entries=entries)
    with pytest.raises(ValueError):node.install_node(spec,tmp_path/'node')
    assert not (tmp_path/'outside').exists() and not (tmp_path/'node').exists()
