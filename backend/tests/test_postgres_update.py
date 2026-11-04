import pytest

from operations.configuration import ConfigurationError
from operations.configuration import validate_postgres_lock
from operations.control import validate_postgres_update


@pytest.mark.parametrize('target',['17-alpine3.24','18-bookworm','17-trixie','17-alpine3.25','17'])
def test_in_place_update_refuses_major_or_os_volume_change(target):
    old='library/postgres:17-bookworm@sha256:'+'a'*64
    new='library/postgres:'+target+'@sha256:'+'b'*64
    with pytest.raises(ConfigurationError,match='new volume'):
        validate_postgres_update(old,new)


def test_same_major_and_distribution_digest_update_is_allowed():
    validate_postgres_update('library/postgres:17-bookworm@sha256:'+'a'*64,
                             'postgres:17.7-bookworm@sha256:'+'b'*64)


def test_same_apk_storage_family_digest_update_is_allowed():
    family='postgresql17-apk-alpine3.24'
    validate_postgres_update('library/alpine:3.24@sha256:'+'a'*64,
                            'alpine:3.24@sha256:'+'b'*64,family,family)


@pytest.mark.parametrize('previous,target,old_family,new_family',[
    ('postgres:17-alpine3.24','alpine:3.24',None,'postgresql17-apk-alpine3.24'),
    ('alpine:3.24','postgres:17-alpine3.24','postgresql17-apk-alpine3.24',None),
    ('alpine:3.24','alpine:3.24','postgresql17-apk-alpine3.24','postgresql18-apk-alpine3.24'),
    ('alpine:3.24','alpine:3.25','postgresql17-apk-alpine3.24','postgresql17-apk-alpine3.25'),
    ('alpine:3.24','alpine:3.25','postgresql17-apk-alpine3.24','postgresql17-apk-alpine3.24'),
    ('alpine:3.24','alpine:3.24',None,None),
])
def test_package_family_transition_requires_separate_logical_restore(previous,target,old_family,new_family):
    with pytest.raises(ConfigurationError,match='new volume'):
        validate_postgres_update(previous+'@sha256:'+'a'*64,target+'@sha256:'+'b'*64,old_family,new_family)


@pytest.mark.parametrize('major,client', [('18','17.11-r0'),('17','18.0-r0')])
def test_storage_label_cannot_hide_changed_package_major(major,client):
    lock={'images':{'postgres':'alpine:3.24@sha256:'+'a'*64},'postgresStorageFamily':'postgresql17-apk-alpine3.24',
          'postgresPackages':{'postgresql'+major:'17.11-r0','postgresql17-client':client,'postgresql17-contrib':'17.11-r0'}}
    with pytest.raises(ConfigurationError,match='package versions'):
        validate_postgres_lock(lock)
