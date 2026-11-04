"""Start a local ClamAV engine and test real signed databases and INSTREAM.

Engine recognition and the portal freshness gate are reported separately. An
engine-only success never approves stale signatures or certifies publication.
"""
import argparse
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
EICAR = b'X5O!P%@AP[4'+bytes([92])+b'PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*'


def message(port, command, data=None):
    with socket.create_connection(('127.0.0.1', port), timeout=15) as stream:
        stream.sendall(command)
        if data is not None:
            stream.sendall(struct.pack('!I', len(data))+data+bytes(4))
        result = b''
        while len(result) < 8192:
            part = stream.recv(1024)
            if not part:
                break
            result += part
            if b'\0' in part:
                break
        return result.rstrip(b'\0').decode()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--clamd', required=True)
    parser.add_argument('--database', required=True)
    parser.add_argument('--certificates', required=True)
    parser.add_argument('--library-dir')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    for name in ['clamd', 'database', 'certificates']:
        value = str(Path(getattr(args, name)).resolve())
        if any(c in value for c in '\n\r'):
            raise ValueError('Invalid path')
        setattr(args, name, value)
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    from portal.file_processing import clamav_scan, ProcessingError
    with tempfile.TemporaryDirectory(prefix='portal-clamav-probe-') as directory:
        config = Path(directory)/'clamd.conf'
        config.write_text(f'DatabaseDirectory {args.database}\nCVDCertsDirectory {args.certificates}\nTCPSocket {port}\nTCPAddr 127.0.0.1\nForeground yes\nMaxThreads 2\nStreamMaxLength 21M\nMaxScanSize 100M\nMaxFileSize 21M\nAlertExceedsMax yes\n')
        env = dict(os.environ)
        if args.library_dir:
            env['LD_LIBRARY_PATH'] = str(Path(args.library_dir).resolve())
        with (Path(directory)/'engine.log').open('wb') as log:
            process = subprocess.Popen([args.clamd, '--config-file', str(config)], env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic()+90
                version = None
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError('ClamAV exited during database validation')
                    try:
                        version = message(port, b'zVERSION\0')
                        break
                    except OSError:
                        time.sleep(.5)
                if version is None:
                    raise RuntimeError('ClamAV did not become available')
                clean = b'name,position\nsynthetic,specialist\n'
                clean_result = message(port, b'zINSTREAM\0', clean)
                eicar_result = message(port, b'zINSTREAM\0', EICAR)
                gate = {'passed': False}
                try:
                    provenance = clamav_scan(clean, '127.0.0.1', port)
                    try:
                        clamav_scan(EICAR, '127.0.0.1', port)
                        gate = {'passed': False, 'error': 'EICAR_NOT_REJECTED'}
                    except ProcessingError as error:
                        gate = {'passed': error.code == 'MALWARE_DETECTED', 'eicarError': error.code, **provenance}
                except ProcessingError as error:
                    gate = {'passed': False, 'error': error.code}
                value = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'scope': __doc__,
                         'engineVersion': version, 'engineOnly': {'clean': clean_result, 'eicar': eicar_result,
                         'passed': clean_result == 'stream: OK' and eicar_result.endswith(' FOUND')},
                         'productionFreshnessGate': gate, 'fullPublicationPipeline': 'NOT_TESTED'}
                target = Path(args.output)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(value, indent=2)+'\n')
                print(json.dumps(value, indent=2))
                if not value['engineOnly']['passed']:
                    raise SystemExit(1)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
