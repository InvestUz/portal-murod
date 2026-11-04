"""Live loopback HTTP acceptance of Django, cookies, CSRF and three roles.

SQLite locally; this does not certify browser rendering, TLS/VPN, PostgreSQL or
an approved-file pipeline. No AV decision is mocked or bypassed in this test.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import parse_qs, urlsplit
import pytest
import requests
from django.contrib.auth.models import User
from portal.models import UserAccount

pytestmark = pytest.mark.django_db(transaction=True)


class HTTP:
    def __init__(self, origin):
        self.origin = origin
        self.session = requests.Session()
        self.session.trust_env = False
        self.token = self.call('GET', '/auth/csrf')['csrfToken']

    def call(self, method, path, body=None, expected=200, files=None):
        headers = {'Origin': self.origin}
        if method != 'GET':
            headers['X-CSRFToken'] = self.token
        response = self.session.request(method, self.origin+'/api/v1'+path,
                                        json=body if files is None else None,
                                        files=files, data=body if files else None,
                                        headers=headers, timeout=10, allow_redirects=False)
        assert response.status_code == expected, (method, path, response.status_code)
        result = response.json()
        if isinstance(result, dict) and result.get('csrfToken'):
            self.token = result['csrfToken']
        return result

    def enrol(self, username, temporary):
        state = self.call('POST', '/auth/login', {'username': username, 'password': temporary})
        assert state['mustChangePassword'] and not state['mfaEnrolled']
        self.call('GET', '/employees', expected=403)
        password = secrets.token_urlsafe(32)
        self.call('POST', '/me/change-password', {'currentPassword': temporary, 'newPassword': password})
        uri = self.call('POST', '/me/mfa/start', {'password': password})['totpURI']
        parameters = parse_qs(urlsplit(uri).query)
        secret = parameters['secret'][0]
        key = base64.b32decode(secret+'='*((-len(secret)) % 8))
        step = int(parameters.get('period', ['30'])[0])
        counter = int(time.time())//step
        digest = hmac.new(key, struct.pack('!Q', counter), hashlib.sha1).digest()
        offset = digest[-1] & 15
        value = (struct.unpack('!I', digest[offset:offset+4])[0] & 0x7fffffff) % 1000000
        self.call('POST', '/me/mfa/verify', {'code': str(value).zfill(6)})
        assert self.call('GET', '/me')['mfaVerified']

    def close(self):
        self.session.close()


def test_three_roles_over_real_http_with_password_mfa_privacy_trash_and_revocation(live_server, settings, org):
    settings.APP_ORIGIN = live_server.url
    settings.CSRF_TRUSTED_ORIGINS = [live_server.url]
    settings.ALLOWED_HOSTS = ['localhost', '127.0.0.1', 'testserver']
    initial = secrets.token_urlsafe(32)
    administrator = User.objects.create_user(username='http.admin', password=initial)
    UserAccount.objects.create(user=administrator, role='ADMIN', display_name='Synthetic HTTP administrator', must_change_password=True)
    admin, hr, employee = HTTP(live_server.url), HTTP(live_server.url), HTTP(live_server.url)
    try:
        admin.enrol('http.admin', initial)
        account = admin.call('POST', '/admin/users', {'username': 'http.hr', 'name': 'Synthetic HTTP HR', 'role': 'HR'}, expected=201)
        hr.enrol('http.hr', account['temporaryPassword'])
        hr.call('GET', '/admin/users', expected=403)
        person = hr.call('POST', '/employees', {'displayName': 'Synthetic HTTP colleague', 'positionTitle': 'Specialist',
                                               'unitId': str(org[1].pk), 'officeId': str(org[0].pk), 'extension': '555'}, expected=201)
        account = admin.call('POST', '/admin/users', {'username': 'http.employee', 'name': 'Synthetic HTTP employee',
                                                      'role': 'EMPLOYEE', 'employeeId': person['id']}, expected=201)
        employee.enrol('http.employee', account['temporaryPassword'])
        employee.call('POST', '/employees', {'displayName': 'Forbidden'}, expected=403)
        employee.call('PATCH', '/me/contact', {'mobilePhone': '+998 90 123 45 67', 'mobileVisible': False})
        assert hr.call('GET', '/employees/'+person['id'])['mobilePhone'] == '+998 90 123 45 67'
        other = hr.call('POST', '/employees', {'displayName': 'Hidden synthetic colleague', 'positionTitle': 'Specialist',
                                              'unitId': str(org[1].pk), 'officeId': str(org[0].pk), 'extension': '556',
                                              'mobilePhone': '+998 90 765 43 21', 'mobileVisible': False}, expected=201)
        assert employee.call('GET', '/employees/'+other['id'])['mobilePhone'] is None
        assert employee.call('GET', '/employees?q=765')['total'] == 0
        article = hr.call('POST', '/news', {'title': 'Synthetic live HTTP announcement', 'body': '<p>Company text</p><script>unsafe()</script>',
                                           'category': 'NEWS', 'status': 'PUBLISHED', 'pinned': True}, expected=201)
        assert '<script' not in employee.call('GET', '/news/'+article['id'])['body']
        first = employee.call('POST', '/news/'+article['id']+'/view', {})
        again = employee.call('POST', '/news/'+article['id']+'/view', {})
        assert first['views'] == again['views'] == 1
        hr.call('POST', '/content/news/'+article['id']+'/trash', {})
        employee.call('GET', '/news/'+article['id'], expected=404)
        assert any(row['id'] == article['id'] for row in hr.call('GET', '/trash'))
        hr.call('POST', '/trash/news/'+article['id']+'/restore', {})
        employee.call('GET', '/news/'+article['id'])
        upload = hr.call('POST', '/files', {'purpose': 'IMPORT'}, expected=202,
                         files={'file': ('synthetic.csv', b'name,position\nsynthetic,specialist\n', 'text/csv')})
        assert upload['securityStatus'] == 'QUARANTINED'
        hr.call('GET', '/files/'+upload['id']+'/download', expected=403)
        employee.call('GET', '/files/'+upload['id']+'/download', expected=403)
        hr.call('POST', '/employees/'+person['id']+'/archive', {'confirmDetach': True})
        employee.call('GET', '/me', expected=401)
    finally:
        for client in [admin, hr, employee]:
            client.close()
