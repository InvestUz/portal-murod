#!/usr/bin/env python3
"""Separate Python worker; no Django initialization or database credentials needed."""
import hashlib
import base64
import signal
import json
import os
import subprocess
import sys
import time
import threading
import tempfile
from pathlib import Path
import requests

BASE=Path(__file__).resolve().parents[1]
RUNTIME=Path(os.environ.get('PORTAL_RUNTIME_DIR',str(BASE/'.runtime')))
if not os.environ.get('PORTAL_PROCESSOR') and (RUNTIME/'config.json').exists():
    for key,value in json.loads((RUNTIME/'config.json').read_text()).items():
        os.environ.setdefault(key,str(value))
TOKEN=os.environ.get('WORKER_TOKEN','')
ORIGIN=os.environ.get('WORKER_API_URL','http://127.0.0.1:3000').rstrip('/')
MAX_BYTES=int(os.environ.get('MAX_UPLOAD_BYTES',20*1024*1024))

def execute(job,data):
    """A subprocess bounds each parser; the supervisor stays available after failure."""
    import tempfile
    from portal.file_processing import clamav_scan,ProcessingError
    scan_info=None
    if job['kind']=='SCAN':
        try:scan_info=clamav_scan(data,os.environ.get('CLAMAV_HOST',''),int(os.environ.get('CLAMAV_PORT',3310)))
        except ProcessingError as error:return {'error':error.code}
    with tempfile.TemporaryDirectory(prefix='portal-job-') as directory:
        inp=Path(directory)/'input.bin'
        inp.write_bytes(data)
        spec=Path(directory)/'job.json'
        spec.write_text(json.dumps({k:v for k,v in job.items() if k!='lease'}))
        result=Path(directory)/'result.json'
        keys={'PATH','LANG','LC_ALL','LD_LIBRARY_PATH','PYTHONPATH','MAX_OCR_PAGES','OCR_LANGUAGES','TESSDATA_PREFIX'}
        environment={key:value for key,value in os.environ.items() if key in keys}
        environment['PORTAL_PROCESSOR']='1'
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--task',str(spec),str(inp),str(result)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,env=environment,start_new_session=True)
        try:
            code=process.wait(timeout=600)
            if code or not result.exists():return {'error':'PROCESSOR_FAILED'}
            if result.stat().st_size>7*1024*1024:return {'error':'RESULT_LIMIT'}
            output=json.loads(result.read_text())
            if scan_info is not None and not output.get('error'):
                cleaned=output.get('cleanedBase64')
                if cleaned:
                    derivative=base64.b64decode(cleaned,validate=True)
                    if len(derivative)>MAX_BYTES:return {'error':'RESULT_LIMIT'}
                    try:clamav_scan(derivative,os.environ.get('CLAMAV_HOST',''),int(os.environ.get('CLAMAV_PORT',3310)))
                    except ProcessingError as error:return {'error':error.code}
                # Parser output cannot supply its own approval or scanner provenance.
                output={key:value for key,value in output.items() if key in {'mimeType','cleanedBase64'}}
                output.update(scan_info,status='APPROVED')
            return output
        except subprocess.TimeoutExpired:
            return {'error':'PROCESSOR_TIMEOUT'}
        finally:
            # The parser cannot create a different session/process group or signal its parent.
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait()

def task(spec,input_file,result_file):
    # Per-file process has no bootstrap/lease token or credentials in its environment.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU,(480,480))
    resource.setrlimit(resource.RLIMIT_FSIZE,(100*1024*1024,100*1024*1024))
    resource.setrlimit(resource.RLIMIT_NOFILE,(96,96))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_AS,(1536*1024*1024,1536*1024*1024))
    for key in list(os.environ):
        if any(value in key for value in ['TOKEN','SECRET','PASSWORD','ACCESS_KEY','DATABASE_URL','POSTGRES_']):
            os.environ.pop(key,None)
    from portal.file_processing import inspect_clean_file,extract_text,parse_import,ProcessingError
    from portal.processor_sandbox import restrict_parser
    job=json.loads(Path(spec).read_text())
    data=Path(input_file).read_bytes()
    try:
        restrict_parser()
        if job['kind']=='SCAN':
            result=inspect_clean_file(data,job['fileName'],job['purpose'],int(os.environ.get('MAX_OCR_PAGES',80)))
        elif job['kind']=='EXTRACT':
            result=extract_text(data,job['fileName'],os.environ.get('OCR_LANGUAGES','Latin+uzb_cyrl+rus+eng+tur'),int(os.environ.get('MAX_OCR_PAGES',80)))
        else:
            result=parse_import(data,job['fileName'])
    except ProcessingError as error:
        result={'error':error.code}
    except Exception:
        result={'error':'PROCESSOR_FAILED'}
    Path(result_file).write_text(json.dumps(result,ensure_ascii=False))

def heartbeat_loop(stop):
    session=requests.Session();session.trust_env=False
    try:
        output=subprocess.run(['tesseract','--list-langs'],capture_output=True,text=True,timeout=15,check=True)
        languages=output.stdout.splitlines()[1:]
    except Exception:
        languages=[]
    while not stop.is_set():
        try:
            response=session.post(ORIGIN+'/api/internal/worker/heartbeat',headers={'Authorization':'Bearer '+TOKEN,'X-Forwarded-Proto':'https'},json={'ocrLanguages':languages,'processorSandbox':True},timeout=15)
            response.raise_for_status()
            path=Path(os.environ.get('WORKER_HEALTH_FILE',str(Path(tempfile.gettempdir())/'portal-worker-state'/'health.json')))
            path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if path.parent.stat().st_uid!=os.getuid() or path.parent.stat().st_mode & 0o077:raise OSError('Private health directory required')
            descriptor,name=tempfile.mkstemp(prefix='heartbeat-',dir=path.parent)
            with os.fdopen(descriptor,'w') as stream:json.dump({'seenAt':time.time()},stream)
            Path(name).replace(path)
        except Exception:
            pass  # Health ages out; no credentials or parser output are logged.
        stop.wait(20)


def run():
    # Prevent parser processes with the same uid from reading supervisor secrets via /proc.
    if sys.platform.startswith('linux'):
        import ctypes
        if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:
            raise SystemExit('Could not disable supervisor process dumps.')
    if len(TOKEN)<40:
        raise SystemExit('WORKER_TOKEN is required; run setup first.')
    session=requests.Session()
    # Do not leak internal credentials to an ambient HTTP proxy.
    session.trust_env=False
    check_environment={key:value for key,value in os.environ.items() if key in {'PATH','LANG','LC_ALL','LD_LIBRARY_PATH'}}
    check_environment['PORTAL_PROCESSOR']='1'
    checked=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--sandbox-check'],env=check_environment,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15,check=False)
    if checked.returncode:raise SystemExit('Parser sandbox is unavailable; refusing file processing.')
    stop=threading.Event()
    threading.Thread(target=heartbeat_loop,args=(stop,),daemon=True).start()
    headers={'Authorization':'Bearer '+TOKEN,'X-Forwarded-Proto':'https'}
    while True:
        try:
            response=session.post(ORIGIN+'/api/internal/worker/claim',headers=headers,json={},timeout=15)
            response.raise_for_status()
            job=response.json()['job']
            if not job:
                time.sleep(2)
                continue
            lease={'Authorization':'Bearer '+job['lease'],'X-Forwarded-Proto':'https'}
            response=session.get(ORIGIN+f'/api/internal/worker/{job["id"]}/file',headers=lease,timeout=30,stream=True)
            response.raise_for_status()
            parts=[]
            size=0
            for part in response.iter_content(65536):
                size+=len(part)
                if size>MAX_BYTES:
                    raise ValueError('size')
                parts.append(part)
            data=b''.join(parts)
            result={'error':'CHECKSUM_MISMATCH'} if hashlib.sha256(data).hexdigest()!=job['checksum'] else execute(job,data)
            done=session.post(ORIGIN+f'/api/internal/worker/{job["id"]}/result',headers=lease,json=result,timeout=30)
            done.raise_for_status()
        except KeyboardInterrupt:
            stop.set()
            break
        except Exception as error:
            print(json.dumps({'event':'worker_retry','errorType':type(error).__name__}),flush=True)
            time.sleep(5)

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--sandbox-check':
        from portal.processor_sandbox import restrict_parser
        restrict_parser()
    elif len(sys.argv)>1 and sys.argv[1]=='--task':
        task(*sys.argv[2:5])
    else:
        run()
