"""Download an immutable official source archive and authenticate before installation."""
import hashlib
import json
import os
import re
from pathlib import Path
import tempfile
from urllib.parse import urlsplit
try:
    from .verified_https import open_https as urlopen
except ImportError:
    from verified_https import open_https as urlopen


def download(spec, destination):
    if not re.fullmatch('[a-f0-9]{40}',spec.get('commit','')) or not re.fullmatch('[a-f0-9]{64}',spec.get('sha256','')):
        raise ValueError('Invalid native source identity')
    url=urlsplit(spec['url'])
    if url.scheme!='https' or url.hostname!='codeload.github.com' or url.username or url.password or url.query or url.fragment:
        raise ValueError('Unexpected native source URL')
    if not url.path.startswith('/tesseract-ocr/tesseract/tar.gz/') or not url.path.endswith('/'+spec['commit']):
        raise ValueError('Native source must reference the pinned upstream commit')
    destination=Path(destination)
    digest=hashlib.sha256();size=0;temporary=None
    try:
        with urlopen(spec['url'],allowed_hosts={'codeload.github.com'},timeout=60) as response, tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as stream:
            temporary=Path(stream.name)
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>64*1024*1024:raise ValueError('Native source size limit exceeded')
                digest.update(chunk);stream.write(chunk)
        if digest.hexdigest()!=spec['sha256']:raise ValueError('Native source integrity check failed')
        os.replace(temporary,destination)
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--lock',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args()
    download(json.loads(Path(args.lock).read_text())['tesseract'],args.output)
