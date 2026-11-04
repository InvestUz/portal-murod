import pytest
from portal import models as m
from .test_content_and_files import approved_fixture

pytestmark=pytest.mark.django_db

def make_file(hr,rows):
    user,_,_=hr
    f=approved_fixture(user,'import.csv',b'header\nrow',purpose='IMPORT')
    f.parsed_data={'headers':['employeeNumber','displayName','positionTitle','unit','office'],'rows':rows}
    f.save()
    return f

def test_preview_then_commit_is_atomic_and_idempotent(hr,org):
    _,_,api=hr
    f=make_file(hr,[['','Imported one','Specialist',org[1].name,org[0].name],['','Imported two','Specialist',org[1].name,org[0].name]])
    preview=api.post('/api/v1/employees/import/preview',{'fileId':str(f.id)})
    assert preview.status_code==200,preview.content
    p=preview.json()
    assert not p['errors'] and not m.Employee.objects.filter(display_name='Imported one').exists()
    body={'previewHash':p['previewHash'],'decisions':{}}
    commit=api.post(f'/api/v1/employees/import/{p["id"]}/commit',body)
    assert commit.status_code==200,commit.content
    assert commit.json()['created']==2
    assert api.post(f'/api/v1/employees/import/{p["id"]}/commit',body).status_code==409
    assert m.Employee.objects.filter(display_name__startswith='Imported ').count()==2

def test_invalid_import_does_not_partially_write(hr,org):
    _,_,api=hr
    f=make_file(hr,[['','Valid first','Specialist',org[1].name,org[0].name],['','Invalid second','Specialist','missing unit',org[0].name]])
    p=api.post('/api/v1/employees/import/preview',{'fileId':str(f.id)}).json()
    assert p['errors']
    response=api.post(f'/api/v1/employees/import/{p["id"]}/commit',{'previewHash':p['previewHash'],'decisions':{}})
    assert response.status_code==409
    assert not m.Employee.objects.filter(display_name='Valid first').exists()

def test_namesake_import_requires_explicit_choice(hr,org):
    _,_,api=hr
    m.Employee.objects.create(display_name='Same name',position_title='First',unit=org[1],office=org[0])
    f=make_file(hr,[['','Same name','Second',org[1].name,org[0].name]])
    p=api.post('/api/v1/employees/import/preview',{'fileId':str(f.id)}).json()
    assert p['rows'][0]['suggestedAction']=='CHOOSE'
    endpoint=f'/api/v1/employees/import/{p["id"]}/commit'
    assert api.post(endpoint,{'previewHash':p['previewHash'],'decisions':{}}).status_code==409
    assert api.post(endpoint,{'previewHash':p['previewHash'],'decisions':{'2':'NAMESAKE'}}).status_code==200
    assert m.Employee.objects.filter(display_name='Same name').count()==2

def test_stable_number_update_detects_intervening_change(hr,org):
    _,target,api=hr
    f=make_file(hr,[[target.employee_number,target.display_name,'New position',org[1].name,org[0].name]])
    p=api.post('/api/v1/employees/import/preview',{'fileId':str(f.id)}).json()
    target.position_title='Changed after preview'
    target.save()
    endpoint=f'/api/v1/employees/import/{p["id"]}/commit'
    response=api.post(endpoint,{'previewHash':p['previewHash'],'decisions':{'2':'UPDATE'}})
    assert response.status_code==409 and response.json()['code']=='STALE_IMPORT_PREVIEW'
    target.refresh_from_db()
    assert target.position_title=='Changed after preview'

def test_employee_cannot_preview_or_commit_import(employee):
    _,_,api=employee
    assert api.post('/api/v1/employees/import/preview',{'fileId':'00000000-0000-0000-0000-000000000000'}).status_code==403
