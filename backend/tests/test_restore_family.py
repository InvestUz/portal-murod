from types import SimpleNamespace

import pytest

from operations import backup
from operations.configuration import ConfigurationError


@pytest.mark.parametrize('source,target',[(None,'postgresql17-apk-alpine3.24'),('postgresql17-apk-alpine3.24',None),('postgresql18-apk-alpine3.24','postgresql17-apk-alpine3.24')])
def test_family_mismatch_stops_before_image_or_service_operations(monkeypatch,tmp_path,source,target):
    controller=SimpleNamespace(installation={'hostname':'test.internal'},environment={'POSTGRES_STORAGE_FAMILY':target},backup_key=lambda:b'x'*32)
    monkeypatch.setattr(backup,'authenticate',lambda *args:{'release':'synthetic','postgresStorageFamily':source})
    with pytest.raises(ConfigurationError,match='storage family differs'):
        backup.restore_backup(controller,tmp_path,'test.internal',True)


def test_same_family_reaches_matching_release_guard(monkeypatch,tmp_path):
    family='postgresql17-apk-alpine3.24';calls=[]
    def available(release):calls.append(release);return False
    controller=SimpleNamespace(installation={'hostname':'test.internal'},environment={'POSTGRES_STORAGE_FAMILY':family},backup_key=lambda:b'x'*32,image_available=available)
    monkeypatch.setattr(backup,'authenticate',lambda *args:{'release':'synthetic','postgresStorageFamily':family})
    with pytest.raises(ConfigurationError,match='matching API/worker'):
        backup.restore_backup(controller,tmp_path,'test.internal',True)
    assert calls==['synthetic']
