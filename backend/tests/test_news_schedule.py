"""The editor must be able to round-trip and explicitly clear publication dates."""
from datetime import timedelta

import pytest
from django.utils import timezone
from portal import models as m, services


@pytest.mark.django_db
@pytest.mark.parametrize('category', ['NEWS', 'COMPANY'])
def test_company_category_includes_legacy_news_without_exposing_drafts(hr, employee, category):
    originals = [m.News.objects.create(title=value, category=value, body='Synthetic',
                 author=hr[0], status='PUBLISHED') for value in ['NEWS', 'COMPANY']]
    m.News.objects.create(title='Other', category='TEAM', body='Synthetic', author=hr[0], status='PUBLISHED')
    m.News.objects.create(title='Private draft', category='NEWS', body='Synthetic', author=hr[0], status='DRAFT')
    result = services.news(employee[0], {'category': category})
    assert {item['id'] for item in result['items']} == {str(item.id) for item in originals}
    assert list(m.News.objects.filter(id__in=[item.id for item in originals]).order_by('category').values_list('category', flat=True)) == ['COMPANY', 'NEWS']


@pytest.mark.django_db
def test_news_schedule_read_and_clear(hr):
    _, _, api = hr
    start = timezone.now() + timedelta(days=1)
    end = start + timedelta(days=2)
    created = api.post('/api/v1/news', {
        'title': 'Synthetic scheduled news', 'body': '<p>Schedule</p>',
        'status': 'DRAFT', 'publishedAt': start.isoformat(), 'expiresAt': end.isoformat(),
    })
    assert created.status_code == 201, created.content
    path = '/api/v1/news/' + created.json()['id']
    detail = api.get(path).json()
    assert detail['publishedAt'] == start.isoformat()
    assert detail['expiresAt'] == end.isoformat()
    changed = api.patch(path, {'publishedAt': None, 'expiresAt': None})
    assert changed.status_code == 200, changed.content
    detail = api.get(path).json()
    assert detail['publishedAt'] is None
    assert detail['expiresAt'] is None
