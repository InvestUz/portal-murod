import time
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import BasePermission
from .errors import PortalError
from .security import audit, throttle
from .models import UserAccount,Employee

def requires_mfa(account):
    from django.conf import settings
    return settings.REQUIRE_MFA == 'all' or (settings.REQUIRE_MFA == 'privileged' and account.role in {'HR','ADMIN'})

def requires_password_change(account):
    from django.conf import settings
    return settings.REQUIRE_PASSWORD_CHANGE and account.must_change_password

class PortalSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        # Also protects unauthenticated login against login-CSRF.
        if request.path=='/api/v1/auth/login' and request.method not in {'GET','HEAD','OPTIONS'}:
            self.enforce_csrf(request)
        return super().authenticate(request)

class PortalAccess(BasePermission):
    def has_permission(self, request, view):
        from django.conf import settings
        if not request.user.is_authenticated or not request.user.is_active:
            raise PortalError('AUTH_REQUIRED', 401)
        try:
            account = request.user.portal_account
        except UserAccount.DoesNotExist:
            raise PortalError('ACCOUNT_NOT_PROVISIONED', 403)
        if account.employee_id and not Employee.objects.filter(pk=account.employee_id,status='ACTIVE').exists():
            from django.contrib.auth import logout
            logout(request._request)
            raise PortalError('ACCOUNT_BLOCKED',403)
        if request.session.get('account_version') != account.session_version:
            from django.contrib.auth import logout
            logout(request._request)
            raise PortalError('SESSION_REVOKED',401)
        if not getattr(view, 'allow_unready', False):
            if requires_password_change(account):
                raise PortalError('PASSWORD_CHANGE_REQUIRED',403)
            require_mfa = requires_mfa(account)
            if require_mfa and not request.user.is_verified():
                raise PortalError('MFA_SETUP_REQUIRED' if not request.user.totpdevice_set.filter(confirmed=True).exists() else 'MFA_REQUIRED',403)
        roles = getattr(view, 'required_roles', None)
        if roles and account.role not in roles:
            audit(request.user,'ACCESS_DENIED','API',request.path,outcome='DENIED')
            raise PortalError('FORBIDDEN',403)
        if settings.REQUIRE_MFA != 'none' and getattr(view, 'fresh_required', False) and request.method not in {'GET','HEAD'}:
            if time.time()-request.session.get('authenticated_at',0)>900:
                raise PortalError('REAUTH_REQUIRED',403)
        throttle(f'api:{request.user.pk}', 400, 60)
        return True

class AdminAccess(PortalAccess):
    def has_permission(self,request,view):
        super().has_permission(request,view)
        if request.user.portal_account.role!='ADMIN':
            raise PortalError('FORBIDDEN',403)
        return True
