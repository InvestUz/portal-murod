import json

import pytest

from operations.security_scan import inspect_native_worker


@pytest.mark.parametrize('version,path,passed',[
    ('tesseract 5.5.4','/opt/tesseract/bin/tesseract',True),
    ('tesseract 5.5.2','/opt/tesseract/bin/tesseract',False),
    ('tesseract 5.5.4','/usr/bin/tesseract',False),
])
def test_native_gate_rejects_old_engine_and_wrong_binary(monkeypatch,version,path,passed):
    expected={'format':1,'tesseract':{'version':'5.5.4','sha256':'a'*64}}
    report={'sourceLock':expected,'engine':version,'binary':path,'sha256':'b'*64}
    monkeypatch.setattr('operations.security_scan.subprocess.check_output',lambda *args,**kwargs:json.dumps(report))
    assert inspect_native_worker('isolated-image',expected)['passed'] is passed


def test_native_gate_refuses_missing_or_mismatched_inventory(monkeypatch):
    expected={'format':1,'tesseract':{'version':'5.5.4','sha256':'a'*64}}
    monkeypatch.setattr('operations.security_scan.subprocess.check_output',lambda *args,**kwargs:'{}')
    assert inspect_native_worker('isolated-image',expected)['passed'] is False
