import hashlib
import io

import pytest

from scripts import download_native_source as source


def specification(data):
    commit='a'*40
    return {'commit':commit,'sha256':hashlib.sha256(data).hexdigest(),
            'url':'https://codeload.github.com/tesseract-ocr/tesseract/tar.gz/'+commit}


def test_verified_archive_is_installed_only_after_hash_check(tmp_path,monkeypatch):
    data=b'synthetic upstream source';target=tmp_path/'source.tar.gz'
    target.write_bytes(b'previous verified bytes')
    monkeypatch.setattr(source,'urlopen',lambda *args,**kwargs:io.BytesIO(data))
    bad=specification(data);bad['sha256']='0'*64
    with pytest.raises(ValueError,match='integrity'):
        source.download(bad,target)
    assert target.read_bytes()==b'previous verified bytes'
    assert list(tmp_path.iterdir())==[target]
    source.download(specification(data),target)
    assert target.read_bytes()==data


@pytest.mark.parametrize('url',['http://codeload.github.com/tesseract-ocr/tesseract/tar.gz/',
                                'https://untrusted.invalid/tesseract-ocr/tesseract/tar.gz/',
                                'https://codeload.github.com/other/project/tar.gz/'])
def test_unexpected_source_rejected_before_network(tmp_path,monkeypatch,url):
    def forbidden(*args,**kwargs):raise AssertionError('Unexpected network request')
    monkeypatch.setattr(source,'urlopen',forbidden)
    spec=specification(b'example');spec['url']=url+spec['commit']
    with pytest.raises(ValueError):source.download(spec,tmp_path/'archive')
    assert not list(tmp_path.iterdir())
