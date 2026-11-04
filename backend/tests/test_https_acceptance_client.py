"""Native TLS and real Django auth; fixtures are parsed without AV claims."""
import io
import ssl
import subprocess
import threading
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer,WSGIRequestHandler,make_server
import pytest
from django.contrib.auth.models import User
from django.core.wsgi import get_wsgi_application
from portal.models import UserAccount
from portal.file_processing import inspect_clean_file,extract_text
from operations.http_acceptance import Client,AcceptanceError,origin_allowed,pdf_bytes,docx_bytes,png_bytes


@pytest.mark.parametrize('origin',['http://localhost:18443','https://company.internal:18443','https://user@localhost:18443',
                                  'https://localhost:18443/path','https://localhost:18443?q=x','https://localhost:999999',
                                  'https://localhost:443','https://localhost:18443\r\nX:bad'])
def test_https_acceptance_cannot_target_company_or_insecure_origins(origin):
    assert not origin_allowed(origin)
    with pytest.raises(AcceptanceError):Client(origin,'must-not-be-opened.pem')


def test_generated_fixtures_are_real_documents_and_images():
    from PIL import Image
    assert inspect_clean_file(pdf_bytes(),'acceptance.pdf','DOCUMENT',80)['mimeType']=='application/pdf'
    assert 'ORIGINAL REVISION ONE'in extract_text(pdf_bytes(),'acceptance.pdf','eng',80)['text']
    assert inspect_clean_file(docx_bytes(),'acceptance.docx','DOCUMENT',80)['mimeType'].endswith('wordprocessingml.document')
    assert 'ЎЗБЕКЧА ҲУЖЖАТ'in extract_text(docx_bytes(),'acceptance.docx','eng',80)['text']
    assert inspect_clean_file(png_bytes(),'acceptance.png','PHOTO',80)['mimeType']=='image/jpeg'
    with Image.open(io.BytesIO(png_bytes()))as image:assert image.size==(32,32)


@pytest.mark.django_db(transaction=True)
def test_real_django_login_password_mfa_and_secure_cookies_over_native_tls(settings,tmp_path):
    from operations.http_acceptance import NoRedirect
    cert,key=tmp_path/'cert.pem',tmp_path/'key.pem'
    subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','2','-keyout',str(key),'-out',str(cert),
                    '-subj','/CN=localhost','-addext','subjectAltName=DNS:localhost'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    class Server(ThreadingMixIn,WSGIServer):daemon_threads=True
    class Handler(WSGIRequestHandler):
        def get_environ(self):
            value=super().get_environ();value['wsgi.url_scheme']='https';return value
        def log_message(self,*args):pass
    server=make_server('127.0.0.1',0,get_wsgi_application(),server_class=Server,handler_class=Handler)
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
    server.socket=context.wrap_socket(server.socket,server_side=True)
    origin='https://localhost:'+str(server.server_port)
    settings.APP_ORIGIN=origin;settings.CSRF_TRUSTED_ORIGINS=[origin];settings.ALLOWED_HOSTS=['localhost','127.0.0.1']
    settings.SESSION_COOKIE_SECURE=True;settings.CSRF_COOKIE_SECURE=True
    import secrets
    password=secrets.token_urlsafe(32);user=User.objects.create_user(username='tls.admin',password=password)
    UserAccount.objects.create(user=user,role='ADMIN',display_name='Synthetic TLS Administrator',must_change_password=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        client=Client(origin,cert);client.enrol('tls.admin',password)
        assert client.call('GET','/me')['mfaVerified'] and any(cookie.secure for cookie in client.cookies)
        with pytest.raises(ssl.SSLError):
            ssl.create_default_context().wrap_socket(__import__('socket').create_connection(('127.0.0.1',server.server_port),timeout=5),server_hostname='localhost')
        assert NoRedirect().redirect_request(None,None,302,'Found',{},'https://example.invalid')is None
    finally:server.shutdown();server.server_close();thread.join(timeout=5)
