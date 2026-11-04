import os
import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice
from portal.models import Office,OrgUnit,Employee,UserAccount

os.environ.setdefault('APP_ENV','test')
TEST_PASSWORD='TestOnly-P0rtal!57-not-production'

class API:
    def __init__(self):
        self.client=Client(enforce_csrf_checks=True)
        self.token=self.client.get('/api/v1/auth/csrf').json()['csrfToken']
    def call(self,method,path,data=None,csrf=True):
        headers={'HTTP_ORIGIN':settings.APP_ORIGIN}
        if csrf:
            headers['HTTP_X_CSRFTOKEN']=self.token
        response=getattr(self.client,method.lower())(path,data=data if method=='GET' else data or {},content_type='application/json',**headers)
        if response.get('Content-Type','').startswith('application/json'):
            result=response.json()
            if isinstance(result,dict) and result.get('csrfToken'):
                self.token=result['csrfToken']
        return response
    def get(self,path,data=None):return self.call('GET',path,data)
    def post(self,path,data=None):return self.call('POST',path,data)
    def patch(self,path,data=None):return self.call('PATCH',path,data)
    def delete(self,path,data=None):return self.call('DELETE',path,data)

@pytest.fixture(autouse=True)
def runtime_settings(settings,tmp_path):
    settings.MEDIA_ROOT=tmp_path/'files'
    settings.SECURE_SSL_REDIRECT=False
    settings.REQUIRE_MFA='all'
    settings.REQUIRE_PASSWORD_CHANGE=True
    settings.WORKER_TOKEN='test-worker-only-'+('x'*48)
    settings.STORAGE_DRIVER='local'
    settings.STORAGES={'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'}}

@pytest.fixture
def org(db):
    office=Office.objects.create(name='Test office')
    unit=OrgUnit.objects.create(name='Test department')
    return office,unit

@pytest.fixture
def factory(db,org):
    counter=[0]
    def create(role='EMPLOYEE',linked=True,ready=True):
        counter[0]+=1
        n=counter[0]
        user=User.objects.create_user(username=f'test.user.{n}',password=TEST_PASSWORD)
        employee=Employee.objects.create(display_name=f'Synthetic person {n}',position_title='Test specialist',office=org[0],unit=org[1]) if linked else None
        UserAccount.objects.create(user=user,role=role,display_name=f'Test {n}',employee=employee,must_change_password=not ready)
        device=TOTPDevice.objects.create(user=user,name='Test factor',confirmed=True) if ready else None
        client=API()
        response=client.post('/api/v1/auth/login',{'username':user.username,'password':TEST_PASSWORD})
        assert response.status_code==200,response.content
        if ready:
            code=str(totp(device.bin_key,step=device.step,t0=device.t0,digits=device.digits,drift=device.drift)).zfill(6)
            response=client.post('/api/v1/me/mfa/verify',{'code':code})
            assert response.status_code==200,response.content
        return user,employee,client
    return create

@pytest.fixture
def hr(factory):return factory('HR')

@pytest.fixture
def admin(factory):return factory('ADMIN')

@pytest.fixture
def employee(factory):return factory('EMPLOYEE')


def assert_documented_fields(serializer, value):
    from rest_framework import serializers
    if isinstance(serializer, serializers.ListSerializer):
        for item in value:
            assert_documented_fields(serializer.child, item)
    elif isinstance(serializer, serializers.Serializer):
        assert isinstance(value, dict)
        assert not set(value)-set(serializer.fields), 'Undocumented response fields: '+str(set(value)-set(serializer.fields))
        for name, field in serializer.fields.items():
            if name in value and value[name] is not None:
                assert_documented_fields(field, value[name])


@pytest.fixture(autouse=True)
def validate_public_response_contracts(monkeypatch):
    """Every existing API/security test also validates its actual response payload."""
    from portal.contracts import RESPONSES, BINARY_VIEWS, Error, Health
    original = Client.request
    def request(client, **kwargs):
        response = original(client, **kwargs)
        if not response.get('Content-Type', '').startswith('application/json'):
            return response
        match = getattr(response.wsgi_request, 'resolver_match', None)
        view = getattr(getattr(match, 'func', None), 'view_class', None)
        name = view.__name__ if view else None
        if name not in RESPONSES and name not in BINARY_VIEWS:
            return response
        method = response.wsgi_request.method.lower()
        if name == 'ReadyView' and response.status_code == 503:
            contract = Health
        elif response.status_code >= 400:
            contract = Error
        else:
            status, contract = RESPONSES[name][method]
            assert response.status_code == status
        validator = contract() if isinstance(contract, type) else contract
        data = response.json()
        validation = validator.__class__(data=data) if isinstance(contract, type) else __import__('copy').deepcopy(validator)
        if not isinstance(contract, type):
            validation.initial_data = data
        assert validation.is_valid(), (name, method, response.status_code, validation.errors)
        assert_documented_fields(validator, data)
        return response
    monkeypatch.setattr(Client, 'request', request)
