import datetime as dt
import json
from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from portal import models as m
from portal.auth_views import provision_account
from portal.permissions import requires_password_change,requires_mfa

class Command(BaseCommand):
    help='Idempotent synthetic demo seed; forbidden in production.'
    def handle(self,*args,**options):
        if settings.PRODUCTION:
            raise CommandError('Demo seed is forbidden in production.')
        if User.objects.filter(username='demo.admin').exists():
            self.stdout.write('Demo already exists; no passwords or data overwritten.')
            return
        with transaction.atomic():
            offices=[m.Office.objects.create(name=name) for name in ['Markaziy ofis · DEMO','Loyiha ofisi · DEMO','Şahar ofisi · DEMO']]
            root=m.OrgUnit.objects.create(name='Namoyiş kompaniyasi',type='COMPANY')
            units=[m.OrgUnit.objects.create(name=name,parent=root,type='DEPARTMENT',sort_order=i) for i,name in enumerate(['Rahbariyat · DEMO','Xaridlar bölimi · DEMO','Kadrlar bölimi · DEMO','Loyihalar bölimi · DEMO','Yuridik bölim · DEMO','IT xizmati · DEMO'])]
            positions=['Direktor · DEMO','Yetakçi mutaxassis · DEMO','HR mutaxassisi · DEMO','Loyiha menejeri · DEMO','Yurist · DEMO','IT mutaxassisi · DEMO']
            employees=[]
            today=timezone.localdate()
            for i in range(24):
                next_date=today+dt.timedelta(days=(i*3+2)%60)
                birthday=dt.date(1990+i%10,next_date.month,next_date.day)
                e=m.Employee.objects.create(display_name=f'Namoyiş xodimi {i+1:02d}',position_title=positions[i%6],unit=units[i%6],office=offices[i%3],manager=employees[0] if employees else None,extension=str(100+i),mobile_phone=f'+998 00 000 {i//100:02d} {i%100:02d}',mobile_visible=i!=4,birthday=birthday,birthday_visible=i!=5,floor=str(i%3+1) if i%3==0 else '',room=str(200+i) if i%4==0 else '')
                employees.append(e)
            for index,u in enumerate(units):
                u.head=employees[index]
                u.save()
            credentials=[]
            for username,name,role,employee in [('demo.admin','Demo administrator','ADMIN',employees[5]),('demo.hr','Demo HR mutaxassisi','HR',employees[2]),('demo.employee','Demo xodim','EMPLOYEE',employees[1])]:
                user,password=provision_account(None,username,name,role,employee)
                credentials.append({'username':username,'temporaryPassword':password,'role':role,'mustChangePassword':requires_password_change(user.portal_account),'mfa':'required' if requires_mfa(user.portal_account) else 'not_required'})
            admin=User.objects.get(username='demo.admin')
            stories=[
                ('Bir jamoa. Umumiy maqsad.','Jamoa yangiliklari, hamkasblar va muhim hujjatlar — bir joyda.','<p>Bu namoyiş nashri. Portal imkoniyatlarini sinab köriş uçun tayyorlangan; kompaniyaning haqiqiy xabari emas.</p>','COMPANY',True),
                ('Kerakli hamkasbni tez toping','Lavozim, ofis va aloqa raqami böyiça qidiring.','<p>Namoyiş xodimlari kartalarini oçib, tuzilma va rahbarga ötişni tekşiring. Ma’lumotlar sun’iy.</p>','TEAM',False),
                ('Hujjatlar uçun yagona makon','Amaldagi va oldingi tahrirlar özaro boğlangan.','<p>Bu imkoniyatning tavsifi, haqiqiy normativ hujjat emas. Yuklangan fayllar avval xavfsizlik tekşiruvidan ötadi.</p>','DOCUMENTS',False),
                ('Xuş kelibsiz, yangi jamoa a’zolari','Hamkasblar bilan tanishing va aloqada böling.','<p>Namoyiş e’loni. Bu xodimlarni işe qabul qiliş haqida haqiqiy bayonot emas.</p>','ANNOUNCEMENT',False),
            ]
            for index,(title,summary,body,category,pinned) in enumerate(stories):
                m.News.objects.create(title=title,summary=summary,body=body,category=category,pinned=pinned,status='PUBLISHED',author=admin,published_at=timezone.now()-dt.timedelta(days=index),translations={'ru':{'title':['Одна команда. Общая цель.','Найдите нужного коллегу','Единое пространство документов','Добро пожаловать в команду'][index],'summary':'Демонстрационная публикация. Данные вымышлены.','body':'<p>Это демонстрационный материал, а не официальная публикация компании.</p>'}})
            # No fake antivirus approval. Documents stay drafts until a real file passes scanning.
            for title,category in [('Xaridlar nizomi · DEMO','REGULATION'),('Ichki tartib qoidalari · DEMO','POLICY'),('Xizmat xati şabloni · DEMO','TEMPLATE')]:
                m.Document.objects.create(title=title,category=category,description='Namoyiş kartasi. Haqiqiy tasdiqlangan hujjat emas. Fayl hali yuklanmagan.',created_by=admin,status='DRAFT')
        path=settings.RUNTIME_DIR/'demo-credentials.json'
        path.write_text(json.dumps(credentials,ensure_ascii=False,indent=2))
        path.chmod(0o600)
        self.stdout.write('Created synthetic demo data. Credentials: .runtime/demo-credentials.json; no secrets printed.')
