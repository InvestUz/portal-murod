import json
import subprocess

import pytest

from operations.security_scan import inspect_prepared_platform


def inventory_root(root):
    (root/'deploy/postgres').mkdir(parents=True)
    packages={'su-exec':'0.3-r0','postgresql17':'17.11-r0','postgresql17-client':'17.11-r0','postgresql17-contrib':'17.11-r0'}
    (root/'deploy/images.lock.json').write_text(json.dumps({'postgresPackages':packages}))
    (root/'deploy/postgres/UPSTREAM.json').write_text(json.dumps({'patchedSha256':'a'*64}))
    return packages


def test_postgres_inventory_queries_installed_packages_without_network(monkeypatch,tmp_path):
    packages=inventory_root(tmp_path)
    calls=[]
    def output(command,**kwargs):
        calls.append(command)
        if command[command.index('--entrypoint')+1]=='sh':
            return '/sbin/su-exec\npostgres (PostgreSQL) 17.11\n'+'a'*64+'  /usr/local/bin/docker-entrypoint.sh\n'
        return json.dumps([{'name':name,'version':version} for name,version in packages.items()])
    monkeypatch.setattr(subprocess,'check_output',output)
    result=inspect_prepared_platform('isolated-candidate','postgres',tmp_path)
    assert result['passed'] is True
    assert '--no-network' in calls[1] and 'installed' in calls[1]


@pytest.mark.parametrize('output',['[]','{}','not json'])
def test_inventory_does_not_approve_missing_package(monkeypatch,tmp_path,output):
    inventory_root(tmp_path)
    def call(command,**kwargs):
        if command[command.index('--entrypoint')+1]=='sh':
            return '/sbin/su-exec\npostgres (PostgreSQL) 17.11\n'+'a'*64+'  entrypoint\n'
        return output
    monkeypatch.setattr(subprocess,'check_output',call)
    assert inspect_prepared_platform('isolated-candidate','postgres',tmp_path)['passed'] is False


@pytest.mark.parametrize('wrong',['none','version','hash','lock'])
def test_compiler_inventory_checks_official_node_binary_and_lock(monkeypatch,tmp_path,wrong):
    (tmp_path/'deploy').mkdir()
    tools={'packages':{'npm':{'version':'12.2.1'},'undici':{'version':'6.29.1'}}}
    native={'version':'24.22.2','binarySha256':'b'*64}
    (tmp_path/'deploy/build-tools.lock.json').write_text(json.dumps(tools))
    (tmp_path/'deploy/node-runtime.lock.json').write_text(json.dumps(native))
    payload={'lock':tools,'nodeLock':native,'nodeSha256':'b'*64,'node':'v24.22.2','npm':'12.2.1','undici':'6.29.1'}
    if wrong=='version':payload['node']='v24.22.1'
    if wrong=='hash':payload['nodeSha256']='c'*64
    if wrong=='lock':payload['nodeLock']={}
    monkeypatch.setattr(subprocess,'check_output',lambda *args,**kwargs:json.dumps(payload))
    assert inspect_prepared_platform('isolated-compiler','frontend-tools',tmp_path)['passed']==(wrong=='none')
