import time
import pytest
from django_otp.oath import totp
from portal.models import UserAccount
from .conftest import API,TEST_PASSWORD

pytestmark=pytest.mark.django_db

def test_unauthenticated_portal_api_is_closed():
    api=API()
    for path in ['/api/v1/employees','/api/v1/documents','/api/v1/news','/api/schema']:
        response=api.get(path)
        assert response.status_code==401,(path,response.content)
    assert api.post('/api/v1/employees',{}).status_code==401

def test_login_requires_csrf_and_exact_origin():
    api=API()
    assert api.call('POST','/api/v1/auth/login',{'username':'x','password':'y'},csrf=False).status_code==403
    response=api.client.post('/api/v1/auth/login',data={'username':'x','password':'y'},content_type='application/json',HTTP_ORIGIN='https://evil.invalid',HTTP_X_CSRFTOKEN=api.token)
    assert response.status_code==403

def test_wrong_and_missing_users_have_same_error(employee):
    user,_,_=employee
    api=API()
    a=api.post('/api/v1/auth/login',{'username':user.username,'password':'incorrect-password'})
    b=api.post('/api/v1/auth/login',{'username':'missing-user','password':'incorrect-password'})
    assert a.status_code==b.status_code==401
    assert a.json()==b.json()=={'code':'INVALID_CREDENTIALS'}

def test_password_change_then_mfa_is_enforced(factory):
    user,e,api=factory(ready=False)
    assert api.get('/api/v1/employees').json()['code']=='PASSWORD_CHANGE_REQUIRED'
    response=api.post('/api/v1/me/change-password',{'currentPassword':TEST_PASSWORD,'newPassword':'Changed-TestOnly-52!Secur3'})
    assert response.status_code==200,response.content
    assert api.get('/api/v1/employees').json()['code']=='MFA_SETUP_REQUIRED'
    response=api.post('/api/v1/me/mfa/start',{'password':'Changed-TestOnly-52!Secur3'})
    assert response.status_code==200
    assert response.json()['totpURI'].startswith('otpauth://')
    device=user.totpdevice_set.get()
    code=str(totp(device.bin_key)).zfill(6)
    response=api.post('/api/v1/me/mfa/verify',{'code':code})
    assert response.status_code==200,response.content
    assert api.get('/api/v1/employees').status_code==200
    user.refresh_from_db()
    assert user.password.startswith('argon2$')

def test_totp_replay_is_rejected(employee):
    user,_,api=employee
    device=user.totpdevice_set.get()
    code=str(totp(device.bin_key)).zfill(6)
    assert api.post('/api/v1/me/mfa/verify',{'code':code}).status_code==400
    device.refresh_from_db()
    assert device.throttling_failure_count>0

@pytest.mark.parametrize('role,allowed',[('EMPLOYEE',False),('HR',True),('ADMIN',True)])
def test_employee_creation_rights_on_direct_api(factory,org,role,allowed):
    user,e,api=factory(role)
    response=api.post('/api/v1/employees',{'displayName':'API created person','positionTitle':'Specialist','unitId':str(org[1].id),'officeId':str(org[0].id)})
    assert response.status_code==(201 if allowed else 403),response.content

def test_hr_cannot_create_accounts_or_assign_roles(hr,employee):
    _,_,api=hr
    user,_,_=employee
    assert api.get('/api/v1/admin/users').status_code==403
    assert api.post('/api/v1/admin/users',{'username':'extra.user','name':'Extra user','role':'ADMIN'}).status_code==403
    assert api.patch(f'/api/v1/admin/users/{user.id}',{'role':'ADMIN'}).status_code==403

def test_self_service_blocks_mass_assignment_and_colleague_id(employee,factory):
    _,e,api=employee
    _,other,_=factory()
    assert api.patch('/api/v1/me/profile',{'mobilePhone':'+998 00 123 45 67','mobileVisible':False,'floor':'2','room':'B-12'}).status_code==200
    e.refresh_from_db()
    assert e.room=='B-12' and not e.mobile_visible
    assert api.patch('/api/v1/me/profile',{'role':'ADMIN','officeId':str(e.office_id)}).status_code==400
    assert api.patch(f'/api/v1/employees/{other.id}',{'mobilePhone':'123'}).status_code==403

def test_mutation_without_csrf_is_rejected(employee):
    _,_,api=employee
    assert api.call('PATCH','/api/v1/me/profile',{'room':'1'},csrf=False).status_code==403

def test_admin_account_creation_is_separate_from_employee(admin,org):
    _,_,api=admin
    e=api.post('/api/v1/employees',{'displayName':'Separate card','positionTitle':'Specialist','unitId':str(org[1].id),'officeId':str(org[0].id)}).json()
    assert not UserAccount.objects.filter(employee_id=e['id']).exists()
    response=api.post('/api/v1/admin/users',{'username':'separate.user','name':'Separate user','role':'EMPLOYEE','employeeId':e['id']})
    assert response.status_code==201,response.content
    assert len(response.json()['temporaryPassword'])>=18
    account=UserAccount.objects.get(user_id=response.json()['id'])
    assert str(account.employee_id)==e['id'] and account.must_change_password

def test_password_reset_preserves_mfa_and_invalidates_old_session(admin,employee):
    _,_,admin_api=admin
    user,e,api=employee
    response=admin_api.post(f'/api/v1/admin/users/{user.id}/reset-password',{})
    assert response.status_code==200
    assert user.totpdevice_set.filter(confirmed=True).exists()
    assert api.get('/api/v1/employees').status_code==401
    assert UserAccount.objects.get(user=user).must_change_password

def test_role_changes_revoke_old_session(admin,employee):
    _,_,admin_api=admin
    user,e,api=employee
    assert admin_api.patch(f'/api/v1/admin/users/{user.id}',{'role':'HR'}).status_code==200
    assert api.get('/api/v1/employees').json()['code']=='SESSION_REVOKED'

def test_last_admin_cannot_be_disabled(admin):
    user,_,api=admin
    assert api.patch(f'/api/v1/admin/users/{user.id}',{'active':False}).status_code==409

def test_idle_expiry_is_server_enforced(employee,settings):
    _,_,api=employee
    session=api.client.session
    session['last_seen_at']=time.time()-settings.SESSION_IDLE_SECONDS-1
    session.save()
    assert api.get('/api/v1/employees').status_code==401

def test_unsupported_signup_and_auth_paths_are_not_public():
    api=API()
    assert api.post('/api/v1/auth/signup',{'role':'ADMIN'}).status_code==404

def test_cookie_flags_and_no_browser_token(employee):
    _,_,api=employee
    response=api.get('/api/v1/me')
    data=response.json()
    assert not any(key in data for key in ['password','sessionToken','accessToken','secret'])
    assert api.client.cookies['ti_session']['httponly']
    assert response['Cache-Control']=='private, no-store'
    assert 'frame-ancestors' in response['Content-Security-Policy']

def test_early_security_rejections_keep_headers_and_disable_caching(employee):
    _,_,api=employee
    response=api.client.patch('/api/v1/me/profile',{'room':'12'},content_type='application/json',HTTP_ORIGIN='https://untrusted.invalid',HTTP_X_CSRFTOKEN=api.token)
    assert response.status_code==403 and response.json()['code']=='ORIGIN_REJECTED'
    for header in ['X-Request-ID','Content-Security-Policy','Permissions-Policy']:
        assert header in response
    assert response['Cache-Control']=='private, no-store'
    session=api.client.session
    session['last_seen_at']=0;session.save()
    response=api.get('/api/v1/me')
    assert response.status_code==401 and response.json()['code']=='SESSION_EXPIRED'
    assert response['Cache-Control']=='private, no-store' and 'Content-Security-Policy' in response

@pytest.mark.parametrize('operation',['create','link'])
def test_account_cannot_be_linked_to_card_archived_after_validation(admin,factory,monkeypatch,operation):
    from portal import auth_views
    from portal.models import Employee,UserAccount
    from django.contrib.auth.models import User
    _,target,_=factory()
    # Remove the fixture link to make the card available for a different account.
    UserAccount.objects.filter(employee=target).update(employee=None)
    user,_,_=factory(linked=False)
    original=auth_views.validated
    def archived_after_validation(*args,**kwargs):
        values=original(*args,**kwargs)
        Employee.objects.filter(pk=target.pk).update(status='ARCHIVED')
        return values
    monkeypatch.setattr(auth_views,'validated',archived_after_validation)
    api=admin[2]
    if operation=='create':
        response=api.post('/api/v1/admin/users',{'username':'race.archived','name':'Archive race fixture','role':'EMPLOYEE','employeeId':str(target.pk)})
        assert not User.objects.filter(username='race.archived').exists()
    else:
        response=api.patch(f'/api/v1/admin/users/{user.pk}',{'employeeId':str(target.pk)})
        assert UserAccount.objects.get(user=user).employee_id is None
    assert response.status_code==409 and response.json()['code']=='REFERENCE_CHANGED'


def test_archived_card_blocks_access_even_if_account_flag_is_inconsistent(employee):
    from portal.models import Employee
    user,card,api=employee
    # Simulate inconsistent legacy/imported state rather than the normal archive service.
    Employee.objects.filter(pk=card.pk).update(status='ARCHIVED')
    assert user.is_active
    response=api.get('/api/v1/employees')
    assert response.status_code==403 and response.json()['code']=='ACCOUNT_BLOCKED'
    assert api.get('/api/v1/me').status_code==401

@pytest.mark.parametrize('payload',[None,42,[],[{'title':'invalid shape'}],'text',True])
def test_non_object_json_is_rejected_as_client_error(hr,payload):
    import json
    from django.conf import settings
    api=hr[2]
    response=api.client.post('/api/v1/news',json.dumps(payload),content_type='application/json',HTTP_ORIGIN=settings.APP_ORIGIN,HTTP_X_CSRFTOKEN=api.token)
    assert response.status_code==400 and response.json()['code']=='VALIDATION_ERROR'
