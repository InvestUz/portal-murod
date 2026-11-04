import datetime as dt
import pytest
from portal import models as m
from portal.domain import normalize,search_date,upcoming_birthday

pytestmark=pytest.mark.django_db

def test_privacy_is_enforced_in_payload_and_search(hr,employee,factory):
    _,_,hr_api=hr
    _,_,api=employee
    _,target,_=factory()
    target.birthday=dt.date(1901,7,14)
    target.mobile_phone='+998 00 987 65 43'
    target.extension='8790'
    target.birthday_visible=False
    target.mobile_visible=False
    target.save()
    response=api.get('/api/v1/employees/'+str(target.id))
    assert response.status_code==200
    data=response.json()
    assert data['birthDay'] is None and data['mobilePhone'] is None and 'birthday' not in data
    assert data['extension']=='8790'
    for query in ['14.07','+998 00 987 65 43','1901-07-14']:
        assert str(target.id) not in [e['id'] for e in api.get('/api/v1/employees',{'q':query}).json()['items']]
    assert str(target.id) in [e['id'] for e in hr_api.get('/api/v1/employees',{'q':'1901-07-14'}).json()['items']]
    assert hr_api.get('/api/v1/employees/'+str(target.id)).json()['birthday']=='1901-07-14'

def test_public_birthday_never_exposes_year(employee):
    _,target,api=employee
    target.birthday=dt.date(1902,11,3)
    target.save()
    response=api.get('/api/v1/employees/'+str(target.id))
    assert response.json()['birthDay']==3
    assert '1902' not in response.content.decode()
    assert api.get('/api/v1/employees',{'q':'03.11'}).json()['total']==1

def test_internal_number_cannot_be_hidden(hr,employee):
    _,target,api=employee
    _,_,hr_api=hr
    target.extension='450'
    target.save()
    assert hr_api.patch('/api/v1/employees/'+str(target.id),{'extensionVisible':False}).status_code==400
    assert api.get('/api/v1/employees/'+str(target.id)).json()['extension']=='450'

def test_minimum_fields_and_namesake_confirmation(hr,org):
    _,_,api=hr
    data={'displayName':'Ali Valiyev','positionTitle':'Specialist','unitId':str(org[1].id),'officeId':str(org[0].id)}
    first=api.post('/api/v1/employees',data)
    assert first.status_code==201,first.content
    second=api.post('/api/v1/employees',{**data,'displayName':'  ALI   VALIYEV  '})
    assert second.status_code==409 and second.json()['code']=='DUPLICATE_NAME'
    assert second.json()['details']['matches'][0]['id']==first.json()['id']
    third=api.post('/api/v1/employees',{**data,'confirmNamesake':True})
    assert third.status_code==201
    assert third.json()['employeeNumber']!=first.json()['employeeNumber']

def test_employee_manager_cycle_is_rejected(hr,factory):
    _,_,api=hr
    _,a,_=factory()
    _,b,_=factory()
    assert api.patch(f'/api/v1/employees/{a.id}',{'managerId':str(b.id)}).status_code==200
    assert api.patch(f'/api/v1/employees/{b.id}',{'managerId':str(a.id)}).status_code==400
    b.refresh_from_db()
    assert b.manager_id is None

def test_organisation_cycle_and_unit_in_use_are_rejected(hr,org):
    _,_,api=hr
    a=org[1]
    b=m.OrgUnit.objects.create(name='Child',parent=a)
    assert api.patch('/api/v1/org-units/'+str(a.id),{'parentId':str(b.id)}).status_code==400
    assert api.patch('/api/v1/org-units/'+str(a.id),{'active':False}).status_code==409

def test_archive_blocks_active_sessions_and_restore_does_not_unblock(hr,employee,admin):
    _,_,hr_api=hr
    user,target,api=employee
    _,_,admin_api=admin
    assert hr_api.post(f'/api/v1/employees/{target.id}/archive',{}).status_code==200
    user.refresh_from_db()
    assert not user.is_active
    assert api.get('/api/v1/employees').status_code==401
    assert hr_api.post(f'/api/v1/employees/{target.id}/restore',{}).status_code==200
    user.refresh_from_db()
    assert not user.is_active
    assert admin_api.patch(f'/api/v1/admin/users/{user.id}',{'active':True}).status_code==200
    assert api.get('/api/v1/employees').status_code==401

def test_last_admin_cannot_be_archived_by_hr(admin,hr):
    _,target,_=admin
    _,_,api=hr
    assert api.post(f'/api/v1/employees/{target.id}/archive',{}).status_code==409

def test_archived_number_is_not_reused(hr,org):
    _,_,api=hr
    data={'displayName':'Before archive','positionTitle':'Specialist','unitId':str(org[1].id),'officeId':str(org[0].id)}
    first=api.post('/api/v1/employees',data).json()
    assert api.post('/api/v1/employees/'+first['id']+'/archive',{}).status_code==200
    second=api.post('/api/v1/employees',{**data,'displayName':'After archive'}).json()
    assert first['employeeNumber']!=second['employeeNumber']

def test_descendant_filter_and_search_normalisation(hr,org):
    _,_,api=hr
    child=m.OrgUnit.objects.create(name='Quyi bölim',parent=org[1])
    target=m.Employee.objects.create(display_name='Shavkat O‘g‘li',position_title='Bosh mutaxassis',unit=child,office=org[0])
    assert str(target.id) in [e['id'] for e in api.get('/api/v1/employees',{'q':'Şavkat'}).json()['items']]
    direct=api.get('/api/v1/employees',{'unitId':str(org[1].id)}).json()
    all_=api.get('/api/v1/employees',{'unitId':str(org[1].id),'descendants':'true'}).json()
    assert all_['total']==direct['total']+1

def test_sql_injection_like_search_does_not_expand_results(employee):
    _,_,api=employee
    assert api.get('/api/v1/employees',{'q':"' OR 1=1 --"}).json()['total']==0

def test_missing_photo_filter_and_export_permissions(hr,employee):
    _,_,api=hr
    _,_,employee_api=employee
    assert api.get('/api/v1/employees',{'withoutPhoto':'true'}).status_code==200
    assert api.get('/api/v1/employees/export',{'format':'xlsx'}).status_code==200
    assert employee_api.get('/api/v1/employees/export').status_code==403

def test_birthday_edge_cases():
    assert normalize('  SHAVKAT O‘G‘LI ')==normalize('Şavkat ÖĞLI')
    assert search_date('1901-01-01',False) is None
    assert search_date('29.02')=={'day':29,'month':2}
    assert search_date('31.02') is None
    assert upcoming_birthday(dt.date(2000,1,1),dt.datetime(2026,12,31,10,tzinfo=dt.timezone.utc))['days']==1
    value=upcoming_birthday(dt.date(2000,2,29),dt.datetime(2027,2,28,10,tzinfo=dt.timezone.utc))
    assert value['day']==29 and value['days']==1
