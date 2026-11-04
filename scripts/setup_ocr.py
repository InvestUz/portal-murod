#!/usr/bin/env python3
"""Install official Tesseract best models with verified hashes; no application secrets."""
import argparse
import hashlib
import os
import tempfile
from pathlib import Path
try:
 from .verified_https import open_https as urlopen
except ImportError:
 from verified_https import open_https as urlopen
COMMIT='e12c65a915945e4c28e237a9b52bc4a8f39a0cec'
MODELS={'eng': '8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba', 'tur': 'e0c3338dc17503dc7d335a507c9ae01b2b46cfd07561171e1e1ac55d85e8e438', 'uzb': '5bd8a1958b3cee68aa225774b89775f3a510dd2141e7d9eb2b5931adca2624c8', 'uzb_cyrl': '13b5f943418d362ed2a445c43777e9244ab70359bcc31a95eb89738ccd6924b1', 'rus': 'b617eb6830ffabaaa795dd87ea7fd251adfe9cf0efe05eb9a2e8128b7728d6b6', 'Latin': 'cf7216998bf7f363f18e3def04cc6b28ae954d2a5a3bdad09f743c9d3538ef35'}
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--destination',required=True);args=parser.parse_args()
 destination=Path(args.destination);destination.mkdir(parents=True,exist_ok=True)
 for name,digest in MODELS.items():
  target=destination/(name+'.traineddata')
  if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()==digest:
   target.chmod(0o644);continue
  with urlopen('https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/'+COMMIT+'/'+('script/' if name=='Latin' else '')+name+'.traineddata',allowed_hosts={'raw.githubusercontent.com'},timeout=60) as response:
   data=response.read(128*1024*1024+1)
  if len(data)>128*1024*1024 or hashlib.sha256(data).hexdigest()!=digest:raise SystemExit('OCR model integrity check failed: '+name)
  with tempfile.NamedTemporaryFile(dir=destination,delete=False) as temp:temp.write(data);temporary=temp.name
  os.chmod(temporary,0o644)
  os.replace(temporary,target)
  print('Installed verified model: '+name)
