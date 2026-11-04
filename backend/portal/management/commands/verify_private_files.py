import hashlib
import json
from django.core.management.base import BaseCommand,CommandError
from portal.models import FileObject

class Command(BaseCommand):
    help='Verify referenced private file bytes against the recorded SHA-256; prints no filenames/PII.'
    def add_arguments(self,parser):parser.add_argument('--stable-only',action='store_true')
    def handle(self,*args,**options):
        checked=0;missing=0;changed=0
        files=FileObject.objects.exclude(rejection_code='DELETED')
        if options['stable_only']:files=files.filter(security_status='APPROVED')
        for file in files.iterator(chunk_size=100):
            try:
                digest=hashlib.sha256();size=0
                with file.file.open('rb') as source:
                    while data:=source.read(1024*1024):digest.update(data);size+=len(data)
                if digest.hexdigest()!=file.checksum or size!=file.size_bytes:changed+=1
            except Exception:
                if FileObject.objects.filter(pk=file.pk).exclude(rejection_code='DELETED').exists():missing+=1
            checked+=1
        report={'checked':checked,'missing':missing,'changed':changed}
        self.stdout.write(json.dumps(report))
        if missing or changed:raise CommandError('Private file integrity check failed.')
