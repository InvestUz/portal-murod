"""External HTTPS and boundary checks with normal certificate validation, no ambient proxy."""
import json
import ssl
from urllib.error import HTTPError
from urllib.request import Request,build_opener,HTTPSHandler,ProxyHandler,HTTPRedirectHandler

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def probe(origin,ca_file=None):
    from .configuration import validate_origin
    origin,_,_=validate_origin(origin)
    context=ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
    opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context),NoRedirect())
    result={}
    for name,path,status,method in [
        ('httpsReadiness','/api/health/ready',200,'GET'),
        ('anonymousDirectoryBlocked','/api/v1/employees',401,'GET'),
        ('anonymousSchemaBlocked','/api/schema',401,'GET'),
        ('workerBrokerNotExposed','/api/internal/worker/claim',404,'POST'),
    ]:
        try:
            request=Request(origin+path,data=b'{}' if method=='POST' else None,method=method,headers={'Content-Type':'application/json'})
            try:response=opener.open(request,timeout=10)
            except HTTPError as error:response=error
            with response:
                body=response.read(65537)
                valid=response.code==status and len(body)<=65536
                if name=='httpsReadiness':valid=valid and json.loads(body).get('status')=='ready'
                result[name]=bool(valid)
        except Exception:result[name]=False
    return result
