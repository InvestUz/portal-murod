"""Real HTTPS API workflows for a disposable loopback portal; no AV bypasses.

Only Python's standard library is needed on the host. Synthetic accounts and
files are used. API acceptance does not certify browser rendering.
"""
import base64
import csv
import hashlib
import hmac
import http.cookiejar
import io
import json
import secrets
import ssl
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib


class AcceptanceError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def origin_allowed(origin):
    if any(ord(c)<=32 or ord(c)==127 for c in origin):return False
    try:
        value=urllib.parse.urlsplit(origin)
        port=value.port
    except ValueError:return False
    return (value.scheme=='https' and value.hostname=='localhost' and not value.username and not value.password
            and not value.query and not value.fragment and value.path=='' and port is not None and 1024<=port<=65535)


class Client:
    def __init__(self,origin,certificate):
        if not origin_allowed(origin):raise AcceptanceError('HTTPS acceptance requires an isolated loopback origin')
        self.origin=origin
        self.context=ssl.create_default_context(cafile=str(certificate))
        self.cookies=http.cookiejar.CookieJar()
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPSHandler(context=self.context),
                                                urllib.request.HTTPCookieProcessor(self.cookies),NoRedirect())
        self.token=''
        self.username=self.password=self.secret=None
        self.last_counter=-1
        self.call('GET','/auth/csrf')

    def request(self,method,path,*,data=None,content_type='application/json',expected=200,binary=False):
        headers={'Origin':self.origin,'Accept':'application/json'}
        if method!='GET':headers['X-CSRFToken']=self.token
        if data is not None:headers['Content-Type']=content_type
        request=urllib.request.Request(self.origin+'/api/v1'+path,data=data,headers=headers,method=method)
        try:response=self.opener.open(request,timeout=30)
        except urllib.error.HTTPError as error:response=error
        with response:
            status=response.status
            raw=response.read(22*1024*1024+1)
        if len(raw)>22*1024*1024:raise AcceptanceError('Unexpectedly large acceptance response')
        if status!=expected:raise AcceptanceError('Unexpected status for '+method+' '+path.split('?')[0]+': '+str(status))
        if binary:return raw
        value=json.loads(raw)
        if isinstance(value,dict) and value.get('csrfToken'):self.token=value['csrfToken']
        return value

    def call(self,method,path,body=None,expected=200):
        return self.request(method,path,data=None if body is None else json.dumps(body).encode(),expected=expected)

    def verify_factor(self):
        if not self.secret:raise AcceptanceError('No enrolled factor')
        counter=int(time.time())//30
        if counter<=self.last_counter:
            time.sleep(31-(int(time.time())%30));counter=int(time.time())//30
        key=base64.b32decode(self.secret+'='*((-len(self.secret))%8))
        digest=hmac.new(key,struct.pack('!Q',counter),hashlib.sha1).digest()
        offset=digest[-1]&15
        number=(struct.unpack('!I',digest[offset:offset+4])[0]&0x7fffffff)%1000000
        self.call('POST','/me/mfa/verify',{'code':str(number).zfill(6)})
        self.last_counter=counter

    def enrol(self,username,temporary):
        state=self.call('POST','/auth/login',{'username':username,'password':temporary})
        if state['mfaEnrolled']:raise AcceptanceError('Expected a newly issued account')
        self.username=username;self.password=temporary
        self.password_change_required=state['mustChangePassword']
        if state['mustChangePassword']:
            self.call('GET','/employees',expected=403)
            self.password=secrets.token_urlsafe(32)
            self.call('POST','/me/change-password',{'currentPassword':temporary,'newPassword':self.password})
        policy=self.call('GET','/me')
        self.mfa_required=policy.get('mfaRequired',True)
        if self.mfa_required:
            uri=self.call('POST','/me/mfa/start',{'password':self.password})['totpURI']
            self.secret=urllib.parse.parse_qs(urllib.parse.urlsplit(uri).query)['secret'][0]
            self.verify_factor()
            if not self.call('GET','/me')['mfaVerified']:raise AcceptanceError('MFA session not retained')
        else:
            self.call('GET','/employees')

    def move_to(self,origin):
        if not origin_allowed(origin):raise AcceptanceError('Invalid recovery origin')
        self.origin=origin

    def login_existing(self):
        self.call('GET','/auth/csrf')
        state=self.call('POST','/auth/login',{'username':self.username,'password':self.password})
        if state['mustChangePassword']:raise AcceptanceError('Restored credentials changed')
        policy=self.call('GET','/me')
        if policy.get('mfaRequired',True):
            if not state['mfaEnrolled']:raise AcceptanceError('Restored MFA changed')
            self.verify_factor()

    def upload(self,name,data,purpose):
        boundary='portal-'+secrets.token_hex(16)
        body=('--'+boundary+'\r\nContent-Disposition: form-data; name="purpose"\r\n\r\n'+purpose+
              '\r\n--'+boundary+'\r\nContent-Disposition: form-data; name="file"; filename="'+name+
              '"\r\nContent-Type: application/octet-stream\r\n\r\n').encode()+data+('\r\n--'+boundary+'--\r\n').encode()
        value=self.request('POST','/files',data=body,content_type='multipart/form-data; boundary='+boundary,expected=202)
        if value['securityStatus']!='QUARANTINED':raise AcceptanceError('Upload did not enter quarantine')
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            state=self.call('GET','/files/'+value['id']+'/security-status')
            if state['securityStatus']=='APPROVED' and (purpose!='IMPORT' or state['importReady']):return state
            if state['securityStatus'] in {'REJECTED','SCAN_ERROR'} or state.get('processingError'):
                raise AcceptanceError('Live file processing failed: '+str(state.get('rejectionCode') or state.get('processingError') or 'UNKNOWN'))
            time.sleep(1)
        raise AcceptanceError('Live file processing timed out')


def pdf_bytes():
    stream=b'BT /F1 18 Tf 50 150 Td (ACCEPTANCE ORIGINAL REVISION ONE) Tj ET'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
             b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    result=b'%PDF-1.4\n';offsets=[0]
    for index,value in enumerate(objects,1):
        offsets.append(len(result));result+=str(index).encode()+b' 0 obj\n'+value+b'\nendobj\n'
    xref=len(result)
    result+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{v:010d} 00000 n \n'.encode() for v in offsets[1:])
    return result+b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n'+str(xref).encode()+b'\n%%EOF\n'


def docx_bytes():
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as package:
        package.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        package.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        package.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>ACCEPTANCE CURRENT REVISION TWO — ЎЗБЕКЧА ҲУЖЖАТ — ÖZBEKÇA HUJJAT</w:t></w:r></w:p><w:sectPr/></w:body></w:document>')
    return output.getvalue()


def png_bytes():
    def chunk(kind,data):return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!IIBBBBB',32,32,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+bytes([40,100,190])*32)*32))+chunk(b'IEND',b'')


def await_extraction(client,document,version):
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        state=client.call('GET','/documents/'+document+'/versions/'+version)
        if state['extractionStatus']=='READY':return state
        if state['extractionStatus']=='ERROR':raise AcceptanceError('Live extraction failed')
        time.sleep(1)
    raise AcceptanceError('Extraction timed out')


def workflows(origin,certificate,credentials,run_id):
    admin=Client(origin,certificate);admin.enrol(credentials['username'],credentials['temporaryPassword'])
    account=admin.call('POST','/admin/users',{'username':'acceptance.hr','name':'Synthetic Acceptance HR','role':'HR'},expected=201)
    hr=Client(origin,certificate);hr.enrol('acceptance.hr',account['temporaryPassword'])
    hr.call('GET','/admin/users',expected=403)
    office=hr.call('POST','/offices',{'name':'Acceptance office '+run_id},expected=201)['id']
    unit=hr.call('POST','/org-units',{'name':'Acceptance unit '+run_id},expected=201)['id']
    data=io.StringIO();writer=csv.writer(data);writer.writerow(['displayName','positionTitle','unit','office','extension'])
    for number in range(150):writer.writerow([f'Acceptance person {number:03} {run_id}','Synthetic specialist','Acceptance unit '+run_id,'Acceptance office '+run_id,str(100+number)])
    uploaded=hr.upload('acceptance.csv',data.getvalue().encode(),'IMPORT')
    preview=hr.call('POST','/employees/import/preview',{'fileId':uploaded['id']})
    if preview['total']!=150 or preview['errors']:raise AcceptanceError('Live import preview differs')
    imported=hr.call('POST','/employees/import/'+preview['id']+'/commit',{'previewHash':preview['previewHash']})
    if imported['created']!=150:raise AcceptanceError('Live import did not create 150 employees')
    ids=[row['id'] for row in imported['items']]
    account=admin.call('POST','/admin/users',{'username':'acceptance.employee','name':'Synthetic Acceptance Employee','role':'EMPLOYEE','employeeId':ids[1]},expected=201)
    employee=Client(origin,certificate);employee.enrol('acceptance.employee',account['temporaryPassword'])
    employee.call('POST','/employees',{'displayName':'Forbidden'},expected=403)
    hr.call('PATCH','/employees/'+ids[0],{'mobilePhone':'+998 90 123 45 67','mobileVisible':False,'birthday':'2000-01-02','birthdayVisible':True})
    colleague=employee.call('GET','/employees/'+ids[0])
    if colleague['mobilePhone'] is not None or 'birthday' in colleague:raise AcceptanceError('Private colleague data leaked')
    if employee.call('GET','/employees?'+urllib.parse.urlencode({'q':'123 45'}))['total']:raise AcceptanceError('Hidden mobile was searchable')
    employee.call('PATCH','/me/contact',{'mobilePhone':'+998 90 765 43 21','mobileVisible':False})
    hr.call('PATCH','/employees/'+ids[1],{'managerId':ids[0]})
    hr.call('PATCH','/org-units/'+unit,{'headEmployeeId':ids[0]})
    photo=hr.upload('acceptance.png',png_bytes(),'PHOTO')
    hr.call('PATCH','/employees/'+ids[0],{'photoFileId':photo['id']})
    if not employee.request('GET','/files/'+photo['id']+'/download',binary=True).startswith(b'\xff\xd8\xff'):raise AcceptanceError('Sanitized photo is not JPEG')
    duplicates={'displayName':'Acceptance person 000 '+run_id,'positionTitle':'Namesake specialist','unitId':unit,'officeId':office}
    if hr.call('POST','/employees',duplicates,expected=409)['code']!='DUPLICATE_NAME':raise AcceptanceError('Duplicate not detected')
    hr.call('POST','/employees',{**duplicates,'confirmNamesake':True},expected=201)
    document=hr.call('POST','/documents',{'title':'Acceptance policy '+run_id,'category':'POLICY'},expected=201)['id']
    original=pdf_bytes();file1=hr.upload('acceptance-v1.pdf',original,'DOCUMENT')
    v1=hr.call('POST','/documents/'+document+'/versions',{'label':'1','fileId':file1['id']},expected=201)['id']
    await_extraction(hr,document,v1);hr.call('PATCH','/documents/'+document,{'status':'PUBLISHED'})
    current=docx_bytes();file2=hr.upload('acceptance-v2.docx',current,'DOCUMENT')
    v2=hr.call('POST','/documents/'+document+'/versions',{'label':'2','fileId':file2['id']},expected=201)['id']
    await_extraction(hr,document,v2)
    old=employee.call('GET','/documents/'+document+'/versions/'+v1)
    if not old['outdated'] or old['currentVersionId']!=v2:raise AcceptanceError('Historical revision does not link to current')
    for file_id,contents in [(file1['id'],original),(file2['id'],current)]:
        if employee.request('GET','/files/'+file_id+'/download',binary=True)!=contents:raise AcceptanceError('Original revision bytes changed')
    for term in ['CURRENT REVISION TWO','ЎЗБЕКЧА ҲУЖЖАТ','ÖZBEKÇA HUJJAT']:
        result=employee.call('GET','/documents?'+urllib.parse.urlencode({'q':term,'inside':'true'}))
        if not any(item['id']==document for item in result['items']):raise AcceptanceError('Published Word text not searchable')
    hr.call('POST','/content/documents/'+document+'/trash',{})
    employee.call('GET','/documents/'+document+'/versions/'+v1,expected=404)
    employee.call('GET','/files/'+file1['id']+'/download',expected=403)
    hr.call('POST','/trash/documents/'+document+'/restore',{})
    employee.call('GET','/documents/'+document+'/versions/'+v1)
    article=hr.call('POST','/news',{'title':'Acceptance announcement '+run_id,'body':'<p>Synthetic acceptance news</p>','status':'PUBLISHED','pinned':True},expected=201)['id']
    employee.call('POST','/news/'+article+'/view',{})
    if employee.call('POST','/news/'+article+'/view',{})['views']!=1:raise AcceptanceError('Repeated opening counted twice')
    hr.call('POST','/content/news/'+article+'/trash',{});employee.call('GET','/news/'+article,expected=404)
    hr.call('POST','/trash/news/'+article+'/restore',{})
    account=admin.call('POST','/admin/users',{'username':'acceptance.archived','name':'Synthetic Archived Employee','role':'EMPLOYEE','employeeId':ids[-1]},expected=201)
    archived=Client(origin,certificate);archived.enrol('acceptance.archived',account['temporaryPassword'])
    hr.call('POST','/employees/'+ids[-1]+'/archive',{'confirmDetach':True});archived.call('GET','/me',expected=401)
    report={'passed':True,'scope':'Real HTTPS API through Nginx and actual backend/worker/AV; not browser rendering',
            'createdEmployees':151,'importedEmployees':150,'cleanFormats':['CSV','PNG-to-JPEG','PDF','DOCX'],
            'csrfPasswordSession':True,'mfaRequired':employee.mfa_required,
            'forcedPasswordChangeRequired':employee.password_change_required,
            'csrfPasswordMfa':True if employee.mfa_required else None,'rolesAndPrivacy':True,'duplicateAndNamesake':True,'oldAndNewVersionBytes':True,
            'documentSearchInScripts':True,'newsUniqueViewsAndTrash':True,'archiveSessionRevocation':True}
    accounts=[{'username':c.username,'password':c.password,'totpSecret':c.secret}for c in [admin,hr,employee]]
    state={'privateAccounts':accounts,'employee':employee,'document':document,'oldVersion':v1,
           'files':[(file1['id'],hashlib.sha256(original).hexdigest()),(file2['id'],hashlib.sha256(current).hexdigest())]}
    return report,state


def verify_restored(state,origin):
    client=state['employee'];client.move_to(origin);client.call('GET','/me',expected=401);client.login_existing()
    old=client.call('GET','/documents/'+state['document']+'/versions/'+state['oldVersion'])
    if not old['outdated']:raise AcceptanceError('Restored historical revision differs')
    for file_id,digest in state['files']:
        if hashlib.sha256(client.request('GET','/files/'+file_id+'/download',binary=True)).hexdigest()!=digest:raise AcceptanceError('Restored file bytes differ')
    return {'oldSessionRejected':True,'passwordPreserved':True,'passwordAndMfaPreserved':True if client.secret and client.call('GET','/me').get('mfaRequired',True) else None,'historicalVersionAndOriginalBytes':True}
