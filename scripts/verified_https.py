"""Restricted HTTPS downloads for build artifacts; no redirects or proxy inheritance."""
from contextlib import contextmanager
from http.client import HTTPSConnection
import ssl
from urllib.parse import urlsplit


class Download:
    def __init__(self,response,url):self.response=response;self.url=url
    def read(self,size):return self.response.read(size)
    def geturl(self):return self.url


@contextmanager
def open_https(url, *, allowed_hosts, timeout=60):
    parsed=urlsplit(url)
    if (parsed.scheme!='https' or parsed.hostname not in allowed_hosts
            or parsed.username or parsed.password or parsed.port not in {None,443}
            or parsed.query or parsed.fragment or not parsed.path.startswith('/')
            or any(char in url for char in ['\r','\n','\\'])):
        raise ValueError('Unexpected artifact HTTPS URL')
    connection=HTTPSConnection(parsed.hostname,443,timeout=timeout,context=ssl.create_default_context())
    response=None
    try:
        connection.request('GET',parsed.path,headers={'Accept-Encoding':'identity'})
        response=connection.getresponse()
        if response.status!=200:raise ValueError('Artifact HTTPS response must be 200; redirects are refused')
        yield Download(response,url)
    finally:
        if response is not None:response.close()
        connection.close()
