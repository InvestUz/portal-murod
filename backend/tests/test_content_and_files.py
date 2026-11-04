"""APPROVED file fixtures isolate downstream logic; they do NOT test a real AV engine."""
import hashlib
import io
import zipfile
from datetime import timedelta
import pytest
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from portal import models as m
from portal.domain import search_fold
from portal.file_processing import validate_structure,validate_zip,clamav_scan,ProcessingError,parse_import

pytestmark=pytest.mark.django_db

def approved_fixture(user,name='safe.pdf',data=b'%PDF-1.7\nsynthetic test fixture',purpose='DOCUMENT'):
    f=m.FileObject(original_name=name,mime_type='application/pdf',size_bytes=len(data),checksum=hashlib.sha256(data).hexdigest(),purpose=purpose,security_status='APPROVED',scanner_version='TEST-BOUNDARY-FIXTURE-NOT-REAL-AV',signature_version='NOT-SCANNED',created_by=user)
    f.file.save(name,ContentFile(data),save=False)
    f.save()
    return f

def create_doc(hr,old_text='archival needle',new_text='current wording'):
    user,_,api=hr
    d=m.Document.objects.create(title='Synthetic regulation',category='REGULATION',created_by=user,status='PUBLISHED')
    old=m.DocumentVersion.objects.create(document=d,label='1',file=approved_fixture(user,'old.pdf',b'%PDF-1.7\nold fixture'),created_by=user,extraction_status='READY',extracted_text=old_text,normalized_text=search_fold(old_text))
    new=m.DocumentVersion.objects.create(document=d,label='2',file=approved_fixture(user,'new.pdf',b'%PDF-1.7\nnew fixture'),created_by=user,extraction_status='READY',extracted_text=new_text,normalized_text=search_fold(new_text))
    d.current_version=new
    d.save()
    return d,old,new

@pytest.mark.parametrize('role',['HR','ADMIN'])
def test_managers_publish_news_without_approval(factory,role,employee):
    _,_,api=factory(role)
    response=api.post('/api/v1/news',{'title':'Published news','body':'<p>News text</p>','status':'PUBLISHED','pinned':True,'language':'uz'})
    assert response.status_code==201,response.content
    _,_,employee_api=employee
    assert employee_api.get('/api/v1/news/'+response.json()['id']).status_code==200

def test_drafts_and_stored_xss(employee,hr):
    _,_,api=hr
    payload={'title':'Safe title','body':'<p>Hello</p><script>alert(1)</script><img src=x onerror=alert(2)><a href="javascript:alert(3)">x</a>','translations':{'ru':{'body':'<script>bad()</script><p>Текст</p>'}},'status':'DRAFT'}
    response=api.post('/api/v1/news',payload)
    id=response.json()['id']
    _,_,ordinary=employee
    assert ordinary.get('/api/v1/news/'+id).status_code==404
    result=api.get('/api/v1/news/'+id).json()
    assert '<script' not in result['body'] and 'javascript:' not in result['body'] and 'onerror' not in result['body']
    assert '<script' not in result['translations']['ru']['body']
    assert ordinary.post('/api/v1/news',payload).status_code==403

def test_only_explicit_full_open_counts_once(hr,employee,factory):
    user,_,api=hr
    n=m.News.objects.create(title='Views',body='<p>Test</p>',status='PUBLISHED',author=user,published_at=timezone.now())
    _,_,ordinary=employee
    assert ordinary.get('/api/v1/news').status_code==200
    assert ordinary.get('/api/v1/news/'+str(n.id)).json()['views']==0
    assert ordinary.post(f'/api/v1/news/{n.id}/view',{}).json()['views']==1
    assert ordinary.post(f'/api/v1/news/{n.id}/view',{}).json()['views']==1
    _,_,other=factory()
    assert other.post(f'/api/v1/news/{n.id}/view',{}).json()['views']==2
    response=other.get('/api/v1/news/'+str(n.id)).json()
    assert 'readers' not in response and 'viewers' not in response

def test_old_version_remains_readable_and_has_current_link(hr,employee):
    d,old,new=create_doc(hr)
    _,_,api=employee
    result=api.get(f'/api/v1/documents/{d.id}/versions/{old.id}')
    assert result.status_code==200,result.content
    assert result.json()['outdated'] is True
    assert result.json()['document']['currentVersionId']==str(new.id)
    response=api.get(f'/api/v1/files/{old.file_id}/download')
    assert b''.join(response.streaming_content)==b'%PDF-1.7\nold fixture'
    response=api.get(f'/api/v1/files/{new.file_id}/download')
    assert b''.join(response.streaming_content)==b'%PDF-1.7\nnew fixture'
    assert api.patch(f'/api/v1/documents/{d.id}/versions/{old.id}',{'fileId':str(new.file_id)}).status_code==405

def test_document_search_defaults_to_current_and_advanced_can_find_history(hr,employee):
    d,old,new=create_doc(hr)
    _,_,api=employee
    assert api.get('/api/v1/documents',{'q':'archival needle'}).json()['total']==0
    assert api.get('/api/v1/documents',{'q':'archival needle','inside':'true'}).json()['total']==0
    found=api.get('/api/v1/documents',{'q':'archival needle','inside':'true','history':'true'}).json()
    assert found['total']==1 and found['items'][0]['versionId']==str(old.id) and found['items'][0]['outdated']

def test_document_trash_restore_and_permanent_delete(hr,employee):
    d,old,new=create_doc(hr)
    _,_,api=hr
    _,_,ordinary=employee
    assert api.post(f'/api/v1/content/documents/{d.id}/trash',{}).status_code==200
    assert ordinary.get('/api/v1/documents/'+str(d.id)).status_code==404
    assert ordinary.get(f'/api/v1/files/{old.file_id}/download').status_code==403
    assert ordinary.get('/api/v1/trash').status_code==403
    assert api.post(f'/api/v1/trash/documents/{d.id}/restore',{}).status_code==200
    assert ordinary.get('/api/v1/documents/'+str(d.id)).status_code==200
    api.post(f'/api/v1/content/documents/{d.id}/trash',{})
    assert api.delete(f'/api/v1/trash/documents/{d.id}',{'confirmation':'wrong'}).status_code==400
    assert api.delete(f'/api/v1/trash/documents/{d.id}',{'confirmation':d.title}).status_code==200
    assert not m.Document.objects.filter(pk=d.pk).exists()
    assert not m.DocumentVersion.objects.filter(document_id=d.pk).exists()
    assert api.get(f'/api/v1/files/{old.file_id}/download').status_code==403
    assert api.post(f'/api/v1/files/{old.file_id}/security-status',{}).status_code==409

def test_upload_quarantine_and_antivirus_failure_do_not_allow_download(hr):
    user,_,api=hr
    uploaded=SimpleUploadedFile('example.pdf',b'%PDF-1.7\nnot executable test data',content_type='application/pdf')
    response=api.client.post('/api/v1/files',{'file':uploaded,'purpose':'DOCUMENT'},HTTP_ORIGIN=settings.APP_ORIGIN,HTTP_X_CSRFTOKEN=api.token)
    assert response.status_code==202,response.content
    f=m.FileObject.objects.get(pk=response.json()['id'])
    assert f.security_status=='QUARANTINED'
    assert api.get(f'/api/v1/files/{f.id}/download').status_code==403
    worker=api.client
    claim=worker.post('/api/internal/worker/claim',{},content_type='application/json',HTTP_AUTHORIZATION='Bearer '+settings.WORKER_TOKEN)
    job=claim.json()['job']
    result=worker.post(f'/api/internal/worker/{job["id"]}/result',{'error':'ANTIVIRUS_UNAVAILABLE'},content_type='application/json',HTTP_AUTHORIZATION='Bearer '+job['lease'])
    assert result.status_code==200,result.content
    f.refresh_from_db()
    assert f.security_status=='SCAN_ERROR'
    assert api.get(f'/api/v1/files/{f.id}/download').status_code==403
    assert m.ProcessingJob.objects.filter(file=f,kind='EXTRACT').count()==0

def test_normal_users_cannot_approve_or_claim_worker_jobs(employee):
    _,_,api=employee
    assert api.client.post('/api/internal/worker/claim',{},content_type='application/json').status_code==401

def test_stale_worker_lease_surfaces_error_instead_of_hanging(hr):
    user,_,api=hr
    f=approved_fixture(user)
    f.security_status='SCANNING'
    f.save()
    m.ProcessingJob.objects.create(file=f,kind='SCAN',status='RUNNING',attempts=4,lease_expires=timezone.now()-timedelta(minutes=1))
    response=api.client.post('/api/internal/worker/claim',{},content_type='application/json',HTTP_AUTHORIZATION='Bearer '+settings.WORKER_TOKEN)
    assert response.status_code==200
    f.refresh_from_db()
    assert f.security_status=='SCAN_ERROR' and f.rejection_code=='WORKER_RETRY_LIMIT'

def test_pending_file_cannot_be_published_as_document(hr):
    user,_,api=hr
    f=approved_fixture(user)
    f.security_status='QUARANTINED'
    f.save()
    d=m.Document.objects.create(title='Draft',category='OTHER',created_by=user)
    assert api.post(f'/api/v1/documents/{d.id}/versions',{'label':'1','fileId':str(f.id)}).status_code==400
    assert api.patch(f'/api/v1/documents/{d.id}',{'status':'PUBLISHED'}).status_code==400

def test_structure_validation_and_no_av_are_real_fail_closed_checks():
    with pytest.raises(ProcessingError,match='TYPE_MISMATCH'):
        validate_structure(b'MZ synthetic harmless header','fake.pdf','DOCUMENT')
    with pytest.raises(ProcessingError,match='ANTIVIRUS_UNAVAILABLE'):
        clamav_scan(b'harmless text','')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w') as z:
        z.writestr('../outside.txt','harmless test')
    with pytest.raises(ProcessingError,match='UNSAFE_ARCHIVE_PATH'):
        validate_zip(output.getvalue())

def test_import_parser_does_not_execute_formulas():
    import openpyxl
    book=openpyxl.Workbook()
    book.active.append(['displayName','positionTitle'])
    book.active.append(['=1+1','Test'])
    output=io.BytesIO()
    book.save(output)
    with pytest.raises(ProcessingError,match='IMPORT_FORMULA_REJECTED'):
        parse_import(output.getvalue(),'test.xlsx')

def test_database_rejects_overwriting_old_version(hr):
    from django.db import IntegrityError,transaction
    _,old,_=create_doc(hr)
    with pytest.raises(IntegrityError),transaction.atomic():
        m.DocumentVersion.objects.filter(pk=old.pk).update(label='silently replaced')
    old.refresh_from_db()
    assert old.label=='1'

def test_import_sources_are_not_downloadable_even_by_managers(hr):
    source=approved_fixture(hr[0],name='source.csv',data=b'name,position\nsynthetic,specialist',purpose='IMPORT')
    source.parsed_data={'headers':['name','position'],'rows':[['synthetic','specialist']]};source.save()
    assert hr[2].get(f'/api/v1/files/{source.pk}/download').status_code==403
