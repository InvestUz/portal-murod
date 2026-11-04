"""Runtime checks; no public endpoint exposes the detailed results."""
import uuid
from datetime import timedelta
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.utils import timezone
from . import file_processing
from .models import WorkerHeartbeat


def check_runtime():
    checks={}
    try:
        with connection.cursor() as cursor:cursor.execute('SELECT 1')
        checks['database']=True
    except Exception:checks['database']=False
    checks['frontend']=(settings.BASE_DIR/'frontend-dist/index.html').is_file()
    try:
        file_processing.clamav_scan(b'',settings.CLAMAV_HOST,settings.CLAMAV_PORT)
        checks['antivirus']=True
    except Exception:checks['antivirus']=False
    name=None
    try:
        if settings.STORAGE_DRIVER=='filesystem':
            directory=settings.MEDIA_ROOT
            if not directory.is_dir() or directory.stat().st_mode & 0o077:raise OSError('Private directory permissions required')
        name=default_storage.save('health/'+uuid.uuid4().hex,ContentFile(b'portal-private-storage-health'))
        with default_storage.open(name,'rb') as stream:
            checks['storage']=stream.read()==b'portal-private-storage-health'
    except Exception:checks['storage']=False
    finally:
        if name:
            try:default_storage.delete(name)
            except Exception:checks['storage']=False
    try:
        worker=WorkerHeartbeat.objects.filter(name='file-worker',seen_at__gte=timezone.now()-timedelta(seconds=90)).first()
        checks['worker']=bool(worker)
        checks['processorSandbox']=bool(worker and worker.capabilities.get('processorSandbox') is True)
        checks['ocrModels']=bool(worker and not set(settings.OCR_LANGUAGES.split('+'))-set(worker.capabilities.get('ocrLanguages',[])))
    except Exception:
        checks['worker']=False;checks['ocrModels']=False;checks['processorSandbox']=False
    return checks
