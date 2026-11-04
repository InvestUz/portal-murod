"""Synthetic service benchmark in a disposable database; never a production load certificate."""
import hashlib
import json
import math
import os
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, connections
from portal import models as m, services as svc
from portal.domain import search_fold


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument('--output', required=True)

    def handle(self, *args, **options):
        marker=os.environ.get('PORTAL_ACCEPTANCE_RUN_ID','')
        native=(connection.vendor=='postgresql' and re.fullmatch(r'[0-9a-f]{24}',marker)
                and settings.DATABASES['default']['NAME']=='portal_acceptance_bench_'+marker)
        if settings.APP_ENV != 'test' or not settings.RUNTIME_DIR.name.startswith('portal-catalog-') or (connection.vendor!='sqlite' and not native):
            raise CommandError('Use the disposable SQLite wrapper or isolated native acceptance runner')
        user = User.objects.create_user('benchmark', password=None)
        m.UserAccount.objects.create(user=user, display_name='Synthetic benchmark', role='EMPLOYEE', must_change_password=False)
        office = m.Office.objects.create(name='Synthetic office')
        unit = m.OrgUnit.objects.create(name='Synthetic department')
        for index in range(150):
            m.Employee.objects.create(display_name=f'Synthetic colleague {index:03}', position_title='Specialist', office=office, unit=unit)
        for index in range(40):
            text = ('synthetic ordinary searchable document text '*12000)+f' unique-needle-{index:03}'
            file = m.FileObject.objects.create(file=f'not-real-{index}.pdf', original_name=f'synthetic-{index}.pdf',
                                               mime_type='application/pdf', size_bytes=0, checksum=hashlib.sha256(b'').hexdigest(),
                                               purpose='DOCUMENT', security_status='APPROVED', scanner_version='NOT-AV-SCANNED-FIXTURE', created_by=user)
            document = m.Document.objects.create(title=f'Synthetic policy {index:03}', number=str(index), created_by=user, status='PUBLISHED')
            version = m.DocumentVersion.objects.create(document=document, label='1', file=file, created_by=user,
                                                       extraction_status='READY', extracted_text=text, normalized_text=search_fold(text))
            document.current_version = version
            document.save()
        for index in range(20):
            m.News.objects.create(title=f'Synthetic news {index:03}', body='Synthetic content', author=user, status='PUBLISHED')
        operations = {
            'employeeSearch': lambda who: svc.employees(who, {'q': 'colleague 14'}),
            'documentTitleSearch': lambda who: svc.documents(who, {'q': 'policy 03'}),
            'documentContentSearch': lambda who: svc.documents(who, {'q': 'unique-needle-039', 'inside': 'true'}),
            'newsPage': lambda who: svc.news(who, {}),
        }
        phases = []
        for workers in [1, 8]:
            def measure(key):
                connections.close_all()
                try:
                    who = User.objects.select_related('portal_account').get(pk=user.pk)
                    started = time.monotonic()
                    value = operations[key](who)
                    expected={'employeeSearch':10,'documentTitleSearch':10,'documentContentSearch':1,'newsPage':20}
                    if value['total']!=expected[key]:raise ValueError('Unexpected benchmark result count')
                    return {'operation': key, 'milliseconds': (time.monotonic()-started)*1000, 'total': value['total'], 'error': None}
                except Exception as error:
                    return {'operation': key, 'error': type(error).__name__}
                finally:
                    connections.close_all()
            started = time.monotonic()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(measure, list(operations)*25))
            elapsed = time.monotonic()-started
            results = {}
            for key in operations:
                values = sorted(row['milliseconds'] for row in rows if row['operation'] == key and not row['error'])
                results[key] = {'samples': len(values), 'medianMs': round(statistics.median(values), 2) if values else None,
                                'p95Ms': round(values[math.ceil(len(values)*.95)-1], 2) if values else None,
                                'maxMs': round(max(values), 2) if values else None}
            phases.append({'concurrency': workers, 'requests': len(rows), 'errors': [r for r in rows if r['error']],
                           'seconds': round(elapsed, 3), 'operationsPerSecond': round(len(rows)/elapsed, 2), 'results': results})
        value = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'scope': __doc__,
                 'databaseVendor':connection.vendor,
                 'excluded': (['PostgreSQL']if connection.vendor=='sqlite'else[])+['HTTP','TLS','authentication','AV','file bytes','VPN','company hardware'],
                 'dataset': {'employees': 150, 'documents': 40, 'news': 20, 'charactersPerDocument': len(text)},
                 'phases': phases}
        if connection.vendor=='postgresql':
            value['contentQueryPlan']=json.loads(m.DocumentVersion.objects.filter(normalized_text__contains=search_fold('unique-needle-039')).explain(format='json'))
        target = Path(options['output'])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, indent=2)+'\n')
        self.stdout.write(json.dumps(value, indent=2))
        if any(phase['errors'] for phase in phases):
            raise CommandError('Benchmark has request failures')
