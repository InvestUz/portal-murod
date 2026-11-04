import getpass
import sys
import re
from django.core.management.base import BaseCommand,CommandError
from django.contrib.auth.password_validation import validate_password
from portal.models import UserAccount
from portal.auth_views import provision_account

class Command(BaseCommand):
    help='Create first portal admin with hidden password input.'
    def add_arguments(self,parser):
        parser.add_argument('--username',required=True)
        parser.add_argument('--name',required=True)
        parser.add_argument('--password-stdin',action='store_true')
        parser.add_argument('--if-missing',action='store_true')
    def handle(self,*args,**options):
        if not re.fullmatch(r'[a-zA-Z0-9._-]{3,64}',options['username']):raise CommandError('Use a 3–64 character Latin username.')
        if UserAccount.objects.filter(role='ADMIN',user__is_active=True).exists():
            if options['if_missing']:
                self.stdout.write('Existing administrator preserved.');return
            raise CommandError('An active admin already exists. Use the authenticated admin interface.')
        if options['password_stdin']:
            password=sys.stdin.readline(256).rstrip('\r\n')
        else:
            password=getpass.getpass('Initial temporary password (12+ characters): ')
            if password!=getpass.getpass('Repeat password: '):
                raise CommandError('Passwords do not match.')
        if len(password)>128 or not password.strip():raise CommandError('Use a nonempty password of at most 128 characters.')
        validate_password(password)
        provision_account(None,options['username'],options['name'],'ADMIN',password=password)
        from django.conf import settings
        self.stdout.write('Admin created. Sign in with the issued individual username and password.' if settings.REQUIRE_MFA=='none' and not settings.REQUIRE_PASSWORD_CHANGE else 'Admin created. First-login requirements follow the configured authentication policy.')
