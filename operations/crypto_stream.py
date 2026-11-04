"""Authenticated streaming backups. Verify completely before extracting/restoring plaintext."""
import base64
import json
import os
import sys
import tempfile
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

MAGIC=b'TIPB1'
CHUNK=1024*1024


def encrypt(source,destination,key):
    if len(key)!=32:raise ValueError('Invalid backup key')
    nonce=os.urandom(12);header=MAGIC+nonce
    encryptor=Cipher(algorithms.AES(key),modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(header);destination.write(header)
    while chunk:=source.read(CHUNK):destination.write(encryptor.update(chunk))
    destination.write(encryptor.finalize());destination.write(encryptor.tag)


def _decrypt_stream(source,destination,key):
    if len(key)!=32:raise ValueError('Invalid backup key')
    header=source.read(len(MAGIC)+12)
    if len(header)!=len(MAGIC)+12 or not header.startswith(MAGIC):raise ValueError('Invalid backup format')
    decryptor=Cipher(algorithms.AES(key),modes.GCM(header[len(MAGIC):])).decryptor()
    decryptor.authenticate_additional_data(header);tail=b''
    while chunk:=source.read(CHUNK):
        block=tail+chunk
        if len(block)>16:
            plaintext=decryptor.update(block[:-16])
            if destination is not None:destination.write(plaintext)
            tail=block[-16:]
        else:tail=block
    if len(tail)!=16:raise ValueError('Truncated backup')
    plaintext=decryptor.finalize_with_tag(tail)
    if destination is not None:destination.write(plaintext)


def decrypt(source,destination,key):
    """Authenticate all bytes before exposing any plaintext to a consumer.

    A private temporary file contains ciphertext only. Reusing this immutable
    descriptor prevents a changed external source between verification and
    decryption. Memory stays bounded even for multi-gigabyte snapshots.
    """
    if len(key)!=32:raise ValueError('Invalid backup key')
    if destination is None:
        return _decrypt_stream(source,None,key)
    with tempfile.TemporaryFile(mode='w+b') as ciphertext:
        while chunk:=source.read(CHUNK):ciphertext.write(chunk)
        ciphertext.seek(0)
        _decrypt_stream(ciphertext,None,key)
        ciphertext.seek(0)
        _decrypt_stream(ciphertext,destination,key)


def main():
    mode=sys.argv[1]
    # The key arrives on stdin, never in command arguments, environment or output.
    header=sys.stdin.buffer.readline(4097)
    if len(header)>4096 or not header.endswith(b'\n'):raise ValueError('Invalid key header')
    key=base64.b64decode(json.loads(header)['key'],validate=True)
    if mode=='encrypt':encrypt(sys.stdin.buffer,sys.stdout.buffer,key)
    elif mode in {'decrypt','verify'}:decrypt(sys.stdin.buffer,sys.stdout.buffer if mode=='decrypt' else None,key)
    else:raise ValueError('Unknown codec mode')

if __name__=='__main__':
    try:main()
    except Exception:
        print('Backup authentication or stream operation failed.',file=sys.stderr)
        raise SystemExit(1)
