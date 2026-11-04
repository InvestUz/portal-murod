import io
import ssl

import pytest

from scripts import verified_https as https


@pytest.mark.parametrize('url',['http://example.invalid/a','file:///tmp/a',
                              'https://other.invalid/a','https://user@example.invalid/a',
                              'https://example.invalid:444/a','https://example.invalid/a?q=1'])
def test_disallowed_url_refused_before_connection(monkeypatch,url):
    def forbidden(*args,**kwargs):raise AssertionError('Unexpected network connection')
    monkeypatch.setattr(https,'HTTPSConnection',forbidden)
    with pytest.raises(ValueError):
        with https.open_https(url,allowed_hosts={'example.invalid'}):pass


@pytest.mark.parametrize('status',[200,302])
def test_certificate_verification_and_no_redirect(monkeypatch,status):
    calls=[]
    class Response(io.BytesIO):
        def __init__(self):super().__init__(b'authenticated bytes');self.status=status
    class Connection:
        def __init__(self,host,port,timeout,context):
            assert host=='example.invalid' and port==443
            assert context.check_hostname and context.verify_mode==ssl.CERT_REQUIRED
            self.response=Response()
        def request(self,method,path,headers):calls.append((method,path))
        def getresponse(self):return self.response
        def close(self):calls.append('closed')
    monkeypatch.setattr(https,'HTTPSConnection',Connection)
    if status==200:
        with https.open_https('https://example.invalid/a',allowed_hosts={'example.invalid'}) as response:
            assert response.read(30)==b'authenticated bytes'
    else:
        with pytest.raises(ValueError,match='redirects'):
            with https.open_https('https://example.invalid/a',allowed_hosts={'example.invalid'}):pass
    assert calls==[('GET','/a'),'closed']
