"""Native PostgreSQL acceptance cases; skipped, never emulated, on SQLite."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from django.contrib.auth.models import User
from django.db import connection, connections
from portal import models as m, services
from portal.errors import PortalError

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.skipif(connection.vendor != 'postgresql', reason='Requires real PostgreSQL')]


def concurrent(actions):
    barrier = Barrier(len(actions))
    def execute(action):
        connections.close_all()
        try:
            barrier.wait(timeout=10)
            return action()
        finally:
            connections.close_all()
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(execute, actions))


def test_parallel_same_name_creation_requires_explicit_namesake(hr, org):
    actor = hr[0].pk
    data = {'displayName': 'Concurrent synthetic colleague', 'positionTitle': 'Specialist',
            'unitId': str(org[1].pk), 'officeId': str(org[0].pk)}
    def create():
        try:
            return services.save_employee(User.objects.get(pk=actor), data)
        except PortalError as error:
            return {'error': str(error.detail['code'])}
    results = concurrent([create, create])
    assert sum('id' in result for result in results) == 1
    assert [row['error'] for row in results if 'error' in row] == ['DUPLICATE_NAME']
    assert m.Employee.objects.filter(display_name=data['displayName']).count() == 1


def test_parallel_number_allocation_never_reuses_numbers(hr, org):
    actor = hr[0].pk
    def create(index):
        return services.save_employee(User.objects.get(pk=actor),
                                      {'displayName': f'Concurrent unique colleague {index}', 'positionTitle': 'Specialist',
                                       'unitId': str(org[1].pk), 'officeId': str(org[0].pk)})
    results = concurrent([lambda index=index: create(index) for index in range(8)])
    assert len({row['employeeNumber'] for row in results}) == 8


def test_trigram_indexes_are_present_on_real_postgres():
    with connection.cursor() as cursor:
        cursor.execute("SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND indexname IN ('portal_doc_title_trgm','portal_doc_text_trgm')")
        indexes = dict(cursor.fetchall())
    assert set(indexes) == {'portal_doc_title_trgm', 'portal_doc_text_trgm'}
    assert all('USING gin' in definition and 'gin_trgm_ops' in definition for definition in indexes.values())


def test_parallel_import_commit_applies_one_preview_only_once(hr, org):
    from portal import imports
    from .test_imports import make_file
    file = make_file(hr, [['', 'Concurrent imported colleague', 'Specialist', org[1].name, org[0].name]])
    preview = imports.preview_import(hr[0], file.pk)
    actor = hr[0].pk
    def commit():
        try:
            return imports.commit_import(User.objects.get(pk=actor), preview['id'],
                                         {'previewHash': preview['previewHash'], 'decisions': {}})
        except PortalError as error:
            return {'error': str(error.detail['code'])}
    results = concurrent([commit, commit])
    assert sum(row.get('created', 0) for row in results) == 1
    assert [row['error'] for row in results if 'error' in row] == ['IMPORT_ALREADY_COMMITTED']
    assert m.Employee.objects.filter(display_name='Concurrent imported colleague').count() == 1


def test_parallel_import_previews_recheck_duplicates_and_rollback_entire_loser(hr, org):
    from portal import imports
    from .test_imports import make_file
    previews = []
    for index in range(2):
        file = make_file(hr, [
            ['', f'Concurrent batch unique {index}', 'Specialist', org[1].name, org[0].name],
            ['', 'Concurrent batch shared colleague', 'Specialist', org[1].name, org[0].name],
        ])
        previews.append(imports.preview_import(hr[0], file.pk))
    actor = hr[0].pk
    def commit(preview):
        try:
            return imports.commit_import(User.objects.get(pk=actor), preview['id'],
                                         {'previewHash': preview['previewHash'], 'decisions': {}})
        except PortalError as error:
            return {'error': str(error.detail['code'])}
    results = concurrent([lambda preview=preview: commit(preview) for preview in previews])
    assert sum(row.get('created', 0) for row in results) == 2
    assert [row['error'] for row in results if 'error' in row] == ['DUPLICATE_NAME']
    assert m.Employee.objects.filter(display_name='Concurrent batch shared colleague').count() == 1
    assert m.Employee.objects.filter(display_name__startswith='Concurrent batch unique ').count() == 1
    assert m.ImportJob.objects.filter(pk__in=[p['id'] for p in previews], status='COMMITTED').count() == 1
    assert m.ImportJob.objects.filter(pk__in=[p['id'] for p in previews], status='PREVIEW').count() == 1
