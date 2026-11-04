"""Run the synthetic benchmark in a temporary, automatically removed database."""
import argparse
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='portal-catalog-') as directory:
        env = {**os.environ, 'PORTAL_RUNTIME_DIR': directory, 'APP_ENV': 'test', 'DB_ENGINE': 'sqlite',
               'DJANGO_SECRET_KEY': secrets.token_urlsafe(48)}
        subprocess.run([sys.executable, str(root/'backend/manage.py'), 'migrate', '--noinput'], env=env, check=True, stdout=subprocess.DEVNULL)
        subprocess.run([sys.executable, str(root/'backend/manage.py'), 'benchmark_catalog', '--output', str(Path(args.output).resolve())], env=env, check=True)


if __name__ == '__main__':
    main()
