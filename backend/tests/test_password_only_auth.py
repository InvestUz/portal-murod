import time
import pytest
from portal.models import UserAccount


@pytest.fixture
def password_only(settings):
    settings.REQUIRE_MFA='none'
    settings.REQUIRE_PASSWORD_CHANGE=False


@pytest.mark.django_db
@pytest.mark.parametrize('role',['EMPLOYEE','HR','ADMIN'])
def test_issued_password_opens_portal_without_setup(factory,password_only,role):
    user,_,api=factory(role=role,ready=False)
    assert UserAccount.objects.get(user=user).must_change_password
    me=api.get('/api/v1/me')
    assert me.status_code==200
    assert not me.json()['mustChangePassword']
    assert not me.json()['mfaRequired']
    assert not me.json()['mfaVerified']
    assert api.get('/api/v1/employees').status_code==200
    assert api.get('/api/v1/me').status_code==200
    assert api.get('/api/v1/admin/users').status_code==(200 if role=='ADMIN' else 403)


@pytest.mark.django_db
def test_password_only_session_survives_lunch_break(factory,password_only,settings):
    _,_,api=factory(ready=False)
    session=api.client.session
    session['last_seen_at']=time.time()-3600
    session['login_at']=time.time()-7200
    session.save()
    assert settings.SESSION_COOKIE_AGE==43200
    assert settings.SESSION_IDLE_SECONDS==43200
    assert api.get('/api/v1/employees').status_code==200


@pytest.mark.django_db
def test_password_only_session_still_expires(factory,password_only,settings):
    _,_,api=factory(ready=False)
    session=api.client.session
    session['login_at']=time.time()-settings.SESSION_COOKIE_AGE-1
    session.save()
    response=api.get('/api/v1/employees')
    assert response.status_code==401
    assert response.json()['code']=='SESSION_EXPIRED'


@pytest.mark.django_db
def test_password_only_keeps_csrf_and_logout(factory,password_only):
    _,_,api=factory(ready=False)
    assert api.call('PATCH','/api/v1/me',{'locale':'ru'},csrf=False).status_code==403
    assert api.post('/api/v1/auth/logout').status_code==200
    assert api.get('/api/v1/employees').status_code==401


@pytest.mark.django_db
def test_optional_all_mfa_policy_still_enforced(factory,settings):
    _,_,api=factory(ready=False)
    settings.REQUIRE_MFA='all'
    settings.REQUIRE_PASSWORD_CHANGE=False
    assert api.get('/api/v1/me').json()['mfaRequired']
    assert api.get('/api/v1/employees').json()['code']=='MFA_SETUP_REQUIRED'


@pytest.mark.django_db
def test_english_preference_survives_next_request(factory,password_only):
    _,_,api=factory(ready=False)
    assert api.patch('/api/v1/me',{'locale':'en'}).status_code==200
    assert api.get('/api/v1/me').json()['locale']=='en'
    assert api.patch('/api/v1/me',{'locale':'invalid'}).status_code==400


@pytest.mark.django_db
def test_password_only_still_revokes_blocked_accounts(factory,password_only):
    user,_,employee=factory(ready=False)
    _,_,admin=factory(role='ADMIN',linked=False,ready=False)
    assert admin.patch(f'/api/v1/admin/users/{user.pk}',{'active':False}).status_code==200
    assert employee.get('/api/v1/employees').status_code in {401,403}
