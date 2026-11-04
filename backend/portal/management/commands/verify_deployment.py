import hashlib
import io
import json
import secrets
import time
import uuid
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand,CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone
from PIL import Image,ImageDraw,ImageFont
from portal import models as m,services
from portal.operational import check_runtime
from portal.security import domain_write


def make_probe_pdf():
    image=Image.new('RGB',(1800,1200),'white')
    font=ImageFont.truetype('DejaVuSans.ttf',56)
    ImageDraw.Draw(image).multiline_text((100,180),'PIPELINE CHECK NUMBER 150\nÖZBEKÇA HUJJAT\nЎЗБЕКЧА ҲУЖЖАТ',fill='black',font=font,spacing=35)
    data=io.BytesIO();image.save(data,format='PDF',resolution=150)
    return data.getvalue()


def await_file(file,accepted,deadline):
    while time.monotonic()<deadline:
        file.refresh_from_db()
        if file.security_status in accepted:return file
        if file.security_status in {'SCAN_ERROR','REJECTED'}:raise CommandError('File pipeline did not pass the live security check.')
        time.sleep(1)
    raise CommandError('File pipeline timeout.')


def pipeline_probe(timeout=600):
    actor=m.UserAccount.objects.filter(role='ADMIN',user__is_active=True).select_related('user').first()
    if not actor:raise CommandError('Create an individual administrator before the pipeline check.')
    files=[];document=None;probe_user=None;deadline=time.monotonic()+timeout
    try:
        data=make_probe_pdf();file=m.FileObject(original_name='installation-probe.pdf',mime_type='application/octet-stream',size_bytes=len(data),checksum=hashlib.sha256(data).hexdigest(),purpose='DOCUMENT',created_by=actor.user)
        file.file.save(uuid.uuid4().hex+'.upload',ContentFile(data),save=False)
        with domain_write():file.save();m.ProcessingJob.objects.create(file=file,kind='SCAN')
        files.append(file);await_file(file,{'APPROVED'},deadline)
        document=m.Document.objects.create(title='Installation probe '+secrets.token_hex(8),created_by=actor.user,status='DRAFT')
        version_id=services.add_version(actor.user,document.pk,{'label':'1','fileId':str(file.pk)})['id']
        version=m.DocumentVersion.objects.get(pk=version_id)
        while time.monotonic()<deadline:
            version.refresh_from_db()
            if version.extraction_status=='READY':break
            if version.extraction_status=='ERROR':raise CommandError('Live OCR check failed.')
            time.sleep(1)
        if version.extraction_status!='READY' or 'PIPELINE CHECK NUMBER 150' not in version.extracted_text.upper():raise CommandError('Live OCR output was not found.')
        # Exercise the real publication/search/authorization chain as an employee.
        # This is service-level acceptance, separate from browser UI testing.
        from django.contrib.auth.models import User
        from portal.file_views import authorize_download
        from portal.errors import PortalError
        probe_user=User.objects.create_user(username='pipeline.'+secrets.token_hex(12),password=None)
        m.UserAccount.objects.create(user=probe_user,display_name='Synthetic installation probe',role='EMPLOYEE')
        services.save_document(actor.user,{'status':'PUBLISHED'},document.pk)
        authorize_download(file,probe_user)
        with file.file.open('rb') as original:
            if hashlib.sha256(original.read()).hexdigest()!=file.checksum:raise CommandError('Published file integrity failed.')
        for query in ['PIPELINE CHECK NUMBER 150','ÖZBEKÇA HUJJAT','ЎЗБЕКЧА ҲУЖЖАТ']:
            found=services.documents(probe_user,{'q':query,'inside':'true'})
            if not any(item['id']==str(document.pk) for item in found['items']):raise CommandError('Published scan was not searchable in each script.')
        services.trash(actor.user,'documents',document.pk)
        try:
            authorize_download(file,probe_user)
        except PortalError as error:
            if error.status_code!=403:raise
        else:raise CommandError('Trashed file remained downloadable by an employee.')
        services.restore_content(actor.user,'documents',document.pk)
        authorize_download(file,probe_user)
        # EICAR is a harmless antivirus test signature, assembled only in memory.
        data=(b'X5O!P%@AP[4'+bytes([92])+b'PZX54(P^)7CC)7}'+b'$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*')
        sample=m.FileObject(original_name='antivirus-probe.csv',mime_type='application/octet-stream',size_bytes=len(data),checksum=hashlib.sha256(data).hexdigest(),purpose='IMPORT',created_by=actor.user)
        sample.file.save(uuid.uuid4().hex+'.upload',ContentFile(data),save=False)
        with domain_write():sample.save();m.ProcessingJob.objects.create(file=sample,kind='SCAN')
        files.append(sample)
        await_file(sample,{'REJECTED'},deadline)
        if sample.rejection_code!='MALWARE_DETECTED':raise CommandError('The live antivirus test signature was not detected.')
        if m.ProcessingJob.objects.filter(file=sample,kind__in=['PARSE_IMPORT','EXTRACT']).exists():raise CommandError('A rejected file reached a parser.')
        return {'cleanFileApproved':True,'scannedPdfIndexed':True,'testSignatureBlocked':True,'publishedScanSearchableInEachScript':True,'originalFileIntegrity':True,'trashRevokesEmployeeAccess':True,'restoreRestoresEmployeeAccess':True}
    finally:
        with domain_write():
            if probe_user:probe_user.delete()
            if document:
                document.current_version=None;document.save(update_fields=['current_version']);document.delete()
            for item in files:
                file=m.FileObject.objects.filter(pk=item.pk).first()
                if file and not file.document_versions.exists():
                    file.security_status='REJECTED';file.rejection_code='DELETED';file.save(update_fields=['security_status','rejection_code'])
                    file.jobs.filter(status__in=['PENDING','RUNNING']).update(status='CANCELLED',lease_hash='',lease_expires=None,finished_at=timezone.now())


class Command(BaseCommand):
    help='Machine-readable technical acceptance; nonzero exit if a required check fails.'
    def add_arguments(self,parser):
        parser.add_argument('--pipeline',action='store_true')
        parser.add_argument('--files',action='store_true')
    def handle(self,*args,**options):
        checks=check_runtime()
        checks['postgresql']=connection.vendor=='postgresql'
        try:
            executor=MigrationExecutor(connection)
            checks['migrations']=not executor.migration_plan(executor.loader.graph.leaf_nodes())
            checks['activeAdministrator']=m.UserAccount.objects.filter(role='ADMIN',user__is_active=True).exists()
            if connection.vendor=='postgresql':
                with connection.cursor() as cursor:
                    cursor.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,has_schema_privilege(current_user,'public','CREATE') FROM pg_roles WHERE rolname=current_user")
                    checks['leastPrivilege']=not any(cursor.fetchone())
            else:checks['leastPrivilege']=False
        except Exception:
            checks.update(migrations=False,activeAdministrator=False,leastPrivilege=False)
        report={'release':(settings.BASE_DIR/'RELEASE').read_text().strip(),'checkedAt':timezone.now().isoformat(),'checks':checks,'scope':'Technical acceptance; independent pentest and host/VPN acceptance are separate.'}
        if all(checks.values()) and options['pipeline']:
            try:report['pipeline']=pipeline_probe();checks['pipeline']=True
            except CommandError as error:report['pipeline']={'error':str(error)};checks['pipeline']=False
        if all(checks.values()) and options['files']:
            from django.core.management import call_command
            stream=io.StringIO()
            try:call_command('verify_private_files',stable_only=True,stdout=stream);checks['fileIntegrity']=True
            except CommandError:checks['fileIntegrity']=False
            report['files']=json.loads(stream.getvalue())
        self.stdout.write(json.dumps(report))
        if not all(checks.values()):raise CommandError('Deployment verification failed; inspect the JSON checks above.')
