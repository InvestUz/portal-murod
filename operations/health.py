"""Container health probe. Never prints secrets or private diagnostics."""
import json
import os
import sys
import time
from http.client import HTTPConnection
from pathlib import Path
import tempfile


def main():
    kind=sys.argv[1]
    if kind in {'api-live','api-ready'}:
        connection=HTTPConnection('127.0.0.1',8000,timeout=5)
        try:
            connection.request('GET','/api/health/'+('live' if kind=='api-live' else 'ready'),headers={'X-Forwarded-Proto':'https'})
            response=connection.getresponse()
            if response.status!=200 or json.loads(response.read(65536)).get('status')!=('alive' if kind=='api-live' else 'ready'):raise SystemExit(1)
        finally:connection.close()
    elif kind=='worker':
        path=os.environ.get('WORKER_HEALTH_FILE',str(Path(tempfile.gettempdir())/'portal-worker-state'/'health.json'))
        value=json.load(open(path))
        if not -5<=time.time()-value['seenAt']<=90:raise SystemExit(1)
    else:raise SystemExit(2)

if __name__=='__main__':
    try:main()
    except Exception:raise SystemExit(1)
