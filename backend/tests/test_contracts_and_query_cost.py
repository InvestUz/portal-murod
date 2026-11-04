import ast
from pathlib import Path
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from portal import models as m, services as svc
from portal.contracts import RESPONSES, BINARY_VIEWS

pytestmark = pytest.mark.django_db


def test_every_public_view_method_has_explicit_response_contract():
    root = Path(__file__).resolve().parents[1]/'portal'
    for filename in ['views.py', 'auth_views.py', 'file_views.py']:
        for view in ast.parse((root/filename).read_text()).body:
            if not isinstance(view, ast.ClassDef) or view.name.startswith('Worker'):
                continue
            for method in view.body:
                if isinstance(method, ast.FunctionDef) and method.name in {'get', 'post', 'patch', 'put', 'delete'}:
                    assert view.name in BINARY_VIEWS or method.name in RESPONSES.get(view.name, {})


def test_news_listing_query_count_is_constant_for_many_articles(employee, hr):
    for index in range(25):
        m.News.objects.create(title=f'Synthetic news {index}', body='text', author=hr[0], status='PUBLISHED', published_at=timezone.now())
    with CaptureQueriesContext(connection) as captured:
        result = svc.news(employee[0], {'limit': 25})
    assert len(result['items']) == 25
    assert len(captured) == 2


def test_document_lists_fetch_bounded_snippets_without_complete_text(hr, employee):
    from .test_content_and_files import create_doc
    document, _, version = create_doc(hr, new_text='searchword '+('long text '*100000))
    with CaptureQueriesContext(connection) as captured:
        result = svc.documents(employee[0], {'q': 'searchword', 'inside': 'true'})
    assert result['total'] == 1
    assert result['items'][0]['snippet'].startswith('searchword')
    assert len(result['items'][0]['snippet']) <= 360
    assert len(captured) == 2
    assert 'SUBSTR' in captured[0]['sql'].upper()
    assert 'normalized_text' not in captured[0]['sql'].split(' FROM ')[0]
    history = svc.documents(employee[0], {'q': 'searchword', 'inside': 'true', 'history': 'true'})
    assert history['items'][0]['snippet'].startswith('searchword')


def test_browser_types_match_public_schema():
    from django.core.management import call_command
    call_command('generate_api_types', check=True)


@pytest.mark.django_db(transaction=True)
def test_ocr_migration_preserves_immutable_versions_forwards_and_backwards(hr):
    from django.db import IntegrityError, transaction
    from django.db.migrations.executor import MigrationExecutor
    from .test_content_and_files import create_doc
    document, old, latest = create_doc(hr)
    def assert_immutable():
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('UPDATE portal_documentversion SET label=%s WHERE id=%s', ['replacement', old.pk.hex if connection.vendor == 'sqlite' else old.pk])
    try:
        MigrationExecutor(connection).migrate([('portal', '0004_fold_document_search')])
        assert_immutable()
        MigrationExecutor(connection).migrate([('portal', '0006_document_search_indexes')])
        assert_immutable()
    finally:
        MigrationExecutor(connection).migrate([('portal', '0006_document_search_indexes')])
