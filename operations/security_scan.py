"""Scan pinned bases or locally built final images using an installed Trivy CLI.

All High/Critical findings block the strict gate, including currently unfixed
findings. No automatic CVE suppression or claim of independent penetration test.
"""
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def inspect_native_worker(reference, expected):
    """OS package databases do not inventory our hash-pinned upstream build."""
    script='''import json,pathlib,hashlib,subprocess,shutil
binary=shutil.which('tesseract')
result=subprocess.run([binary,'--version'],capture_output=True,text=True,check=True)
print(json.dumps({'sourceLock':json.loads(pathlib.Path('/usr/share/portal/native-sources.lock.json').read_text()),'engine':result.stdout.splitlines()[0],'binary':binary,'sha256':hashlib.sha256(pathlib.Path(binary).read_bytes()).hexdigest()}))'''
    try:
        command=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
                 '--security-opt','no-new-privileges','--memory','256m','--pids-limit','64',
                 '--entrypoint','python',reference,'-c',script]
        report=json.loads(subprocess.check_output(command,text=True,timeout=60))
        report['passed']=(report['sourceLock']==expected and report['engine']=='tesseract '+expected['tesseract']['version']
                          and report['binary']=='/opt/tesseract/bin/tesseract'
                          and re.fullmatch('[a-f0-9]{64}',report['sha256']) is not None)
        return report
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,TypeError) as error:
        return {'passed':False,'errorType':type(error).__name__}


def inspect_prepared_platform(reference, kind, root):
    """Record the actual helpers/tool versions; scanning alone misses substitutions."""
    command=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
             '--security-opt','no-new-privileges','--memory','256m','--pids-limit','64']
    try:
        if kind=='frontend-tools':
            script='''const fs=require('node:fs'),crypto=require('node:crypto');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const hash=crypto.createHash('sha256'),buffer=Buffer.alloc(1024*1024),fd=fs.openSync('/usr/local/bin/node','r');
let size;while((size=fs.readSync(fd,buffer,0,buffer.length,null))>0)hash.update(buffer.subarray(0,size));fs.closeSync(fd);
console.log(JSON.stringify({lock:read('/usr/share/portal/build-tools.lock.json'),
npm:read('/usr/local/lib/node_modules/npm/package.json').version,
undici:read('/usr/local/lib/node_modules/npm/node_modules/undici/package.json').version,
node:process.version,nodeLock:read('/usr/share/portal/node-runtime.lock.json'),nodeSha256:hash.digest('hex')}));'''
            report=json.loads(subprocess.check_output(command+['--entrypoint','node',reference,'-e',script],text=True,timeout=60))
            expected=json.loads((root/'deploy/build-tools.lock.json').read_text())
            node=json.loads((root/'deploy/node-runtime.lock.json').read_text())
            report['passed']=(report['lock']==expected and report['npm']==expected['packages']['npm']['version']
                              and report['undici']==expected['packages']['undici']['version']
                              and report['nodeLock']==node and report['node']=='v'+node['version']
                              and report['nodeSha256']==node['binarySha256'])
        else:
            script='''test ! -e /usr/local/bin/gosu
grep -F 'exec su-exec postgres "$BASH_SOURCE" "$@"' /usr/local/bin/docker-entrypoint.sh >/dev/null
if grep -q gosu /usr/local/bin/docker-entrypoint.sh; then exit 1; fi
command -v su-exec
postgres --version
sha256sum /usr/local/bin/docker-entrypoint.sh'''
            lines=subprocess.check_output(command+['--entrypoint','sh',reference,'-ec',script],text=True,timeout=60).strip().splitlines()
            if len(lines)!=3:raise ValueError('Unexpected PostgreSQL inventory')
            expected=json.loads((root/'deploy/images.lock.json').read_text())['postgresPackages']
            entrypoint=json.loads((root/'deploy/postgres/UPSTREAM.json').read_text())
            packages=json.loads(subprocess.check_output(command+['--entrypoint','apk',reference,'--no-network',
                                'query','--from','installed','--fields','name,version','--format','json',*sorted(expected)],text=True,timeout=60))
            if not isinstance(packages,list) or len(packages)!=len(expected):raise ValueError('Missing installed PostgreSQL package/helper')
            actual={package['name']:package['version'] for package in packages}
            report={'helper':lines[0],'packages':packages,'postgres':lines[1],'entrypointSha256':lines[2].split()[0]}
            report['passed']=(report['helper']=='/sbin/su-exec' and actual==expected
                              and report['postgres']=='postgres (PostgreSQL) '+expected['postgresql17'].split('-r')[0]
                              and report['entrypointSha256']==entrypoint['patchedSha256'])
        return report
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,TypeError,IndexError) as error:
        return {'passed':False,'errorType':type(error).__name__}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--trivy', default='trivy')
    parser.add_argument('--scope', choices=['base', 'final', 'prepared'], default='base')
    parser.add_argument('--output', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--image-prefix', default='toshkent-invest-portal')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.-]{0,62}',args.image_prefix):
        parser.error('Invalid image prefix')
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    cache = str(Path(args.cache).resolve())
    if args.scope == 'base':
        images = json.loads((root/'deploy/images.lock.json').read_text())['images']
        source = 'remote'
    else:
        release = (root/'RELEASE').read_text().strip()
        kinds=['postgres','frontend-tools'] if args.scope=='prepared' else ['api','worker']
        images = {kind: args.image_prefix+'-'+kind+':'+release for kind in kinds}
        source = 'docker'
    version = subprocess.check_output([args.trivy, '--version'], text=True).splitlines()[0]
    results = []
    for name, reference in images.items():
        report_path = output/(name+'.json')
        command = [args.trivy, 'image', '--image-src', source, '--platform', 'linux/amd64',
                   '--cache-dir', cache, '--scanners', 'vuln', '--format', 'json',
                   '--output', str(report_path), '--timeout', '10m', reference]
        subprocess.run(command, check=True, timeout=700)
        report = json.loads(report_path.read_text())
        counts = {}
        fixable = []
        for target in report.get('Results', []):
            for vulnerability in target.get('Vulnerabilities', []):
                severity = vulnerability['Severity']
                counts[severity] = counts.get(severity, 0)+1
                if severity in {'HIGH', 'CRITICAL'} and vulnerability.get('FixedVersion'):
                    fixable.append({'target': target['Target'], 'id': vulnerability['VulnerabilityID'],
                                    'package': vulnerability['PkgName'], 'installed': vulnerability['InstalledVersion'],
                                    'fixed': vulnerability['FixedVersion'], 'severity': severity})
        item={'name': name, 'reference': reference, 'imageId':report.get('Metadata',{}).get('ImageID'),
              'counts': counts, 'fixableHighCritical': fixable,
              'highCritical': counts.get('HIGH', 0)+counts.get('CRITICAL', 0)}
        if args.scope=='final' and name=='worker':
            expected=json.loads((root/'deploy/native-sources.lock.json').read_text())
            item['nativeComponent']=inspect_native_worker(reference,expected)
        if args.scope=='prepared':
            item['nativeComponent']=inspect_prepared_platform(reference,name,root)
        results.append(item)
    summary = {'generatedAt': datetime.now(timezone.utc).isoformat(), 'tool': version, 'scope': args.scope,
               'scopeNote': {'base':'Unmodified pinned upstream bases; no findings suppressed.',
                             'final':'Built Python application and OCR worker images.',
                             'prepared':'Prepared PostgreSQL image and disposable frontend compiler tools; upstream base findings remain separate.'}[args.scope],
               'passed': not any(row['highCritical'] or not row.get('nativeComponent',{'passed':True})['passed'] for row in results), 'results': results}
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))
    if args.strict and not summary['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
