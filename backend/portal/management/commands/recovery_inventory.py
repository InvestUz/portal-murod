"""Hash stable business records for comparison before/after isolated restoration.

Prints counts and digests, never names, contacts, passwords, session data or keys.
Run while business writes are stopped. verify_private_files checks actual bytes.
"""
import hashlib
import json
from datetime import datetime
from django.contrib.auth.models import User
from django_otp.plugins.otp_totp.models import TOTPDevice
from django.core.management.base import BaseCommand
from django.core.serializers.json import DjangoJSONEncoder
from portal import models as m


class ExactJSONEncoder(DjangoJSONEncoder):
    def default(self,value):
        if isinstance(value,datetime):return value.isoformat()
        return super().default(value)


class Command(BaseCommand):
    def handle(self, *args, **options):
        report = {}
        for model in [m.Office, m.OrgUnit, m.Employee, m.EmployeeNumber, m.News, m.NewsView, m.NewsRevision, m.Document, m.DocumentVersion, m.FileObject, m.ImportJob, m.UserAccount, User, TOTPDevice]:
            fields = [field.attname for field in model._meta.concrete_fields if field.name != 'session_version']
            digest = hashlib.sha256()
            count = 0
            for row in model.objects.order_by('pk').values(*fields).iterator():
                digest.update(json.dumps(row, sort_keys=True, cls=ExactJSONEncoder, separators=(',', ':')).encode())
                digest.update(b'\n')
                count += 1
            report[model.__name__] = {'rows': count, 'sha256': digest.hexdigest()}
        self.stdout.write(json.dumps(report, sort_keys=True))
