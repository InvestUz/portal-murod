"""Extract only the authenticated official Node executable and license for compilation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
try:
    from .verified_https import open_https
except ImportError:
    from verified_https import open_https

MAX_ARCHIVE=128*1024*1024
MAX_EXPANSION=512*1024*1024
MAX_BINARY=256*1024*1024


def install_node(spec,destination):
    version=spec.get('version','')
    if (spec.get('format')!=1 or not re.fullmatch(r'24\.\d+\.\d+',version)
            or spec.get('platform')!='linux-x64-musl'
            or any(not re.fullmatch(r'[a-f0-9]{64}',spec.get(key,'')) for key in ['sha256','binarySha256'])):
        raise ValueError('Invalid Node runtime lock')
    prefix='node-v'+version+'-linux-x64-musl'
    url='https://nodejs.org/dist/v'+version+'/'+prefix+'.tar.xz'
    if spec.get('url')!=url:raise ValueError('Unexpected official Node URL')
    destination=Path(destination)
    if destination.exists() or destination.is_symlink():raise ValueError('Node destination already exists')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.node-',dir=destination.parent) as directory:
        work=Path(directory);archive=work/'node.tar.xz';digest=hashlib.sha256();size=0
        with open_https(url,allowed_hosts={'nodejs.org'},timeout=60) as response,archive.open('xb') as output:
            while chunk:=response.read(1024*1024):
                size+=len(chunk)
                if size>MAX_ARCHIVE:raise ValueError('Node archive size limit')
                digest.update(chunk);output.write(chunk)
        if digest.hexdigest()!=spec['sha256']:raise ValueError('Node archive hash mismatch')
        payload=work/'payload';payload.mkdir();found=set();total=count=0
        selected={prefix+'/bin/node':'node',prefix+'/LICENSE':'LICENSE'}
        with tarfile.open(archive,'r:xz') as package:
            for member in package:
                count+=1;total+=member.size
                if count>50000 or total>MAX_EXPANSION:raise ValueError('Node archive expansion limit')
                # No archive path is ever used as a destination. Nonselected files/links are ignored.
                if member.name not in selected:continue
                if not member.isfile() or member.name in found or not 0<member.size<MAX_BINARY:
                    raise ValueError('Unsafe selected Node member')
                found.add(member.name)
                with package.extractfile(member) as source,(payload/selected[member.name]).open('xb') as output:
                    shutil.copyfileobj(source,output,1024*1024)
        if len(found)!=2:raise ValueError('Node executable/license missing')
        executable=payload/'node'
        with executable.open('rb') as source:
            header=source.read(64);hasher=hashlib.sha256(header)
            while chunk:=source.read(1024*1024):hasher.update(chunk)
        digest=hasher.hexdigest()
        if (len(header)<64 or header[:6]!=b'\x7fELF\x02\x01'
                or int.from_bytes(header[18:20],'little')!=62 or digest!=spec['binarySha256']):
            raise ValueError('Node executable integrity/architecture mismatch')
        executable.chmod(0o755);(payload/'LICENSE').chmod(0o644)
        os.replace(payload,destination)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--lock',required=True);parser.add_argument('--destination',required=True);args=parser.parse_args()
    install_node(json.loads(Path(args.lock).read_text()),args.destination)


if __name__=='__main__':main()
