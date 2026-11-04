import pytest
from drf_spectacular.generators import SchemaGenerator

pytestmark=pytest.mark.django_db

def test_openapi_includes_core_routes_but_excludes_worker():
    schema=SchemaGenerator().get_schema(public=True)
    paths=schema['paths']
    for path in ['/api/v1/employees','/api/v1/documents','/api/v1/news','/api/v1/me','/api/v1/admin/users']:
        assert path in paths
    assert not any('/internal/' in path for path in paths)
    operation_ids=[operation['operationId'] for path in paths.values() for method,operation in path.items() if method in {'get','post','patch','delete'}]
    assert len(operation_ids)==len(set(operation_ids))

def test_schema_is_not_public(employee,admin):
    from django.test import Client
    assert Client().get('/api/schema').status_code==401
    assert employee[2].get('/api/schema').status_code==403
    assert admin[2].get('/api/schema').status_code==200

def test_readiness_fails_closed_without_antivirus(settings,monkeypatch):
    from django.test import Client
    from portal.file_processing import ProcessingError
    def unavailable(*args,**kwargs):raise ProcessingError('ANTIVIRUS_UNAVAILABLE')
    settings.PRODUCTION=True
    monkeypatch.setattr('portal.file_processing.clamav_scan',unavailable)
    assert Client().get('/api/health/ready').status_code==503
    assert Client().get('/api/health/live').status_code==200
