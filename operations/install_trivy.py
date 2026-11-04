"""Fetch an immutable, SHA-256-verified official Trivy release for acceptance CI."""
import argparse
import hashlib
import io
import os
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

VERSION = '0.76.1'
SHA256 = 'c7cbe3137fb8a48a17574bede3dd6beb16742d1e9772929940fc90082c39d9c0'
URL = 'https://github.com/aquasecurity/trivy/releases/download/v'+VERSION+'/trivy_'+VERSION+'_Linux-64bit.tar.gz'


class HTTPSOnlyRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if urlsplit(new_url).scheme != 'https':
            raise ValueError('Scanner downloads require HTTPS for every redirect')
        return super().redirect_request(request, response, code, message, headers, new_url)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    if urlsplit(URL).scheme != 'https':
        raise ValueError('Scanner download requires HTTPS')
    opener = build_opener(HTTPSOnlyRedirect())
    with opener.open(URL, timeout=120) as response:
        data = response.read(80*1024*1024+1)
    if len(data) > 80*1024*1024 or hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('Trivy release integrity check failed')
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        member = archive.getmember('trivy')
        if not member.isfile() or member.size > 200*1024*1024:
            raise ValueError('Invalid Trivy binary')
        executable = archive.extractfile(member).read()
    target = Path(args.output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=target.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(executable)
        os.chmod(name, 0o700)
        os.replace(name, target)
    finally:
        Path(name).unlink(missing_ok=True)
    print('Installed verified Trivy '+VERSION)


if __name__ == '__main__':
    main()
