import json
from django.core.management.base import BaseCommand,CommandError
from django.contrib.sessions.models import Session
from django.db.models import Case,When,F,Value
from portal import models as m
from portal.security import domain_write,audit

class Command(BaseCommand):
    help='Requeue maintenance-interrupted jobs. Only run after stopping all API/worker containers.'
    def add_arguments(self,parser):
        parser.add_argument('--workers-stopped',action='store_true')
        parser.add_argument('--invalidate-sessions',action='store_true')
    def handle(self,*args,**options):
        if not options['workers_stopped']:raise CommandError('Stop all workers/API first and pass --workers-stopped.')
        with domain_write():
            jobs=m.ProcessingJob.objects.filter(status='RUNNING').exclude(file__rejection_code='DELETED')
            scans=list(jobs.filter(kind='SCAN').values_list('file_id',flat=True))
            extracts=list(jobs.filter(kind='EXTRACT').values_list('file_id',flat=True))
            count=jobs.update(status='PENDING',attempts=Case(When(attempts__gt=0,then=F('attempts')-1),default=Value(0)),lease_hash='',lease_expires=None,started_at=None,finished_at=None,error_code='')
            m.FileObject.objects.filter(pk__in=scans,security_status='SCANNING').update(security_status='QUARANTINED')
            m.DocumentVersion.objects.filter(file_id__in=extracts,extraction_status='PROCESSING').update(extraction_status='PENDING')
            if options['invalidate_sessions']:
                Session.objects.all().delete()
                m.UserAccount.objects.update(session_version=F('session_version')+1)
            audit(None,'MAINTENANCE_RECOVERY','SYSTEM',metadata={'requeued':count,'sessionsInvalidated':options['invalidate_sessions']})
        self.stdout.write(json.dumps({'requeued':count,'sessionsInvalidated':options['invalidate_sessions']}))
