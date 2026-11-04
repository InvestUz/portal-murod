"""Fetch hash-pinned compiler tools without executing the old npm installation.

Only used in a disposable build stage. No runtime credentials are accepted.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path, PurePosixPath
try:
    from .verified_https import open_https as urlopen
except ImportError:
    from verified_https import open_https as urlopen


MAX_ARCHIVE = 32 * 1024 * 1024
MAX_EXPANDED = 128 * 1024 * 1024
MAX_MEMBERS = 10000


def install_package(name, spec, parent):
    version = spec['version']
    if name not in {'npm', 'undici'} or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Unexpected build tool or version')
    expected_url = f'https://registry.npmjs.org/{name}/-/{name}-{version}.tgz'
    if spec['url'] != expected_url or not re.fullmatch(r'[a-f0-9]{128}', spec['sha512']):
        raise ValueError('Build tool must use a hash-pinned official registry archive')
    target = parent / name
    if target.exists() or target.is_symlink():
        raise ValueError('Build tool destination must be new')
    with tempfile.TemporaryDirectory(prefix='.tool-', dir=parent) as directory:
        staging = Path(directory)
        archive = staging / 'archive.tgz'
        digest = hashlib.sha512()
        size = 0
        with urlopen(expected_url, allowed_hosts={'registry.npmjs.org'}, timeout=60) as response, archive.open('xb') as output:
            if response.geturl() != expected_url:
                raise ValueError('Unexpected registry redirect')
            while chunk := response.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ARCHIVE:
                    raise ValueError('Build tool archive is too large')
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != spec['sha512']:
            raise ValueError('Build tool archive integrity check failed')
        tree = staging / 'package'
        tree.mkdir(mode=0o755)
        expanded = 0
        seen = set()
        with tarfile.open(archive, 'r:gz') as bundle:
            for count, member in enumerate(bundle, start=1):
                parts = PurePosixPath(member.name).parts
                if (count > MAX_MEMBERS or not parts or parts[0] != 'package'
                        or '\\' in member.name or '..' in parts or member.name.startswith('/')
                        or not (member.isfile() or member.isdir())):
                    raise ValueError('Unsafe build tool archive member')
                relative = PurePosixPath(*parts[1:])
                if not parts[1:]:
                    if member.isdir():
                        continue
                    raise ValueError('Unexpected package root')
                if relative in seen:
                    raise ValueError('Duplicate build tool archive member')
                seen.add(relative)
                destination = tree.joinpath(*parts[1:])
                if member.isdir():
                    destination.mkdir(mode=0o755, parents=True, exist_ok=True)
                    continue
                expanded += member.size
                if member.size < 0 or expanded > MAX_EXPANDED:
                    raise ValueError('Expanded build tool exceeds limit')
                destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
                stream = bundle.extractfile(member)
                if stream is None:
                    raise ValueError('Missing build tool file content')
                with stream, destination.open('xb') as output:
                    shutil.copyfileobj(stream, output, length=1024 * 1024)
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)
        identity = json.loads((tree / 'package.json').read_text(encoding='utf-8'))
        if identity['name'] != name or identity['version'] != version:
            raise ValueError('Build tool package identity mismatch')
        os.replace(tree, target)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--lock', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    lock = json.loads(Path(args.lock).read_text(encoding='utf-8'))
    if lock.get('format') != 1 or set(lock.get('packages', {})) != {'npm', 'undici'}:
        raise ValueError('Unexpected build tool lock')
    destination = Path(args.destination)
    destination.mkdir(mode=0o755, parents=True, exist_ok=False)
    for name, spec in lock['packages'].items():
        install_package(name, spec, destination)


if __name__ == '__main__':
    main()
