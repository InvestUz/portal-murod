"""Run native PostgreSQL tests and a disposable benchmark in the test image.

This is not an application entrypoint. Normal deployments are refused.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from defusedxml import ElementTree as ET

MARKER = 'PORTAL_NATIVE_CHECKS='


def permitted(environment):
    return (environment.get('APP_ENV') == 'test' and environment.get('DB_ENGINE') == 'postgres'
            and environment.get('POSTGRES_HOST') == 'postgres'
            and environment.get('POSTGRES_DB') == 'portal_acceptance'
            and re.fullmatch(r'[0-9a-f]{24}', environment.get('PORTAL_ACCEPTANCE_RUN_ID', '')) is not None)


def main():
    if not permitted(os.environ):
        raise SystemExit('Native checks require an isolated disposable acceptance deployment')
    root = Path(__file__).resolve().parents[1]
    result = {'databaseVendor': 'postgresql', 'tests': {'passed': False}, 'benchmark': {'passed': False}}
    with tempfile.TemporaryDirectory(prefix='portal-native-') as work:
        xml = Path(work)/'pytest.xml'
        run = subprocess.run([sys.executable, '-m', 'pytest', 'backend/tests', '-q', '-p', 'no:cacheprovider',
                              '--junitxml='+str(xml)], cwd=root, check=False, timeout=900)
        counts = {name: 0 for name in ['tests', 'failures', 'errors', 'skipped']}
        if xml.exists():
            for suite in ET.parse(xml).getroot().iter('testsuite'):
                for name in counts:
                    counts[name] += int(suite.get(name, 0))
        result['tests'] = {'passed': run.returncode == 0 and counts['tests'] > 0 and not any(counts[name] for name in ['failures','errors','skipped']), **counts}
        import psycopg
        from psycopg import sql
        name = 'portal_acceptance_bench_'+os.environ['PORTAL_ACCEPTANCE_RUN_ID']
        created = False
        try:
            with psycopg.connect(host='postgres', dbname='postgres', user=os.environ['POSTGRES_USER'],
                                password=os.environ['POSTGRES_PASSWORD'], autocommit=True, connect_timeout=10) as control:
                try:
                    control.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
                    created = True
                    with tempfile.TemporaryDirectory(prefix='portal-catalog-') as directory:
                        output = Path(work)/'catalog.json'
                        env = {**os.environ, 'POSTGRES_DB': name, 'PORTAL_RUNTIME_DIR': directory}
                        subprocess.run([sys.executable, 'backend/manage.py', 'migrate', '--noinput'], cwd=root, env=env, check=True, timeout=300)
                        subprocess.run([sys.executable, 'backend/manage.py', 'benchmark_catalog', '--output', str(output)], cwd=root, env=env, check=True, timeout=300)
                        result['benchmark'] = {'passed': True, 'result': json.loads(output.read_text())}
                finally:
                    if created:
                        control.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        except Exception as error:
            result['benchmark'] = {'passed': False, 'errorType': type(error).__name__}
    print(MARKER+json.dumps(result), flush=True)
    return 0 if result['tests']['passed'] and result['benchmark']['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
