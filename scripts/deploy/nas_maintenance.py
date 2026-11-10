"""Trusted NAS jobs. Online backups fail closed if copied files miss a DB snapshot.

Run with the deployment's maintenance venv, outside the application container.
Credentials stay on the NAS; this never stops services or changes live data.
"""
from contextlib import closing
from datetime import datetime, timezone
import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import urllib.request
from urllib.parse import urlsplit


APP_CONTAINER = 'rkd-ai-app-1'
DB_CONTAINER = 'rkd-ai-database-1'


def now():
    return datetime.now(timezone.utc)


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def pg_tools(directory):
    directory.mkdir()
    wrapper = '''#!{python}
import os,subprocess,sys
from pathlib import Path
tool=Path(sys.argv[0]).name
args=sys.argv[1:]
cmd=['docker','exec']
for key in ('PGHOST','PGPORT','PGUSER','PGPASSWORD','PGDATABASE','PGCONNECT_TIMEOUT'):
    if key in os.environ: cmd.extend(['--env',key])
if tool=='pg_dump':
    index=args.index('--file'); path=args[index+1]; del args[index:index+2]
    with open(path,'wb') as stream:
        result=subprocess.run(cmd+['rkd-ai-database-1',tool]+args,stdout=stream)
else:
    path=args.pop()
    with open(path,'rb') as stream:
        result=subprocess.run(cmd+['-i','rkd-ai-database-1',tool]+args,stdin=stream)
sys.exit(result.returncode)
'''.format(python=sys.executable)
    for name in ('pg_dump', 'pg_restore'):
        path = directory / name
        path.write_text(wrapper)
        path.chmod(0o700)


def backup(root, operations):
    from psycopg.conninfo import make_conninfo
    from rkd_mvp.postgres_backup import create_postgres_backup, _extract
    output = root / 'backups' / ('online-' + now().strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:6])
    output.mkdir(parents=True, mode=0o700)
    report = {'passed': False, 'at': now().isoformat(), 'live_service_stopped': False}
    try:
        if shutil.disk_usage(root).free < 2 * 1024**3:
            raise RuntimeError('insufficient backup disk space')
        image = subprocess.check_output(['docker', 'inspect', APP_CONTAINER, '--format', '{{.Image}}'], text=True).strip()
        for source, name in (('/rkd/runtime', 'runtime'), ('/app', 'application')):
            subprocess.run(['docker', 'cp', APP_CONTAINER + ':' + source, str(output / name)],
                           check=True, capture_output=True, timeout=180)
        pg_tools(output / 'tools')
        dsn = make_conninfo(host='127.0.0.1', port=15432, dbname='rkd_team', user='rkd_owner',
                           password=(root / 'secrets/owner_password').read_text().strip())
        # The existing backup implementation exports one DB read snapshot and
        # checks every referenced byte. New references after docker cp cause a
        # rejected backup, never a published incomplete "successful" archive.
        manifest = create_postgres_backup(dsn, output / 'runtime', output / 'complete.zip',
                                          output / 'application', output / 'tools')
        verified = _extract(output / 'complete.zip', output / 'verified-package')
        assert verified['files'] == manifest['files']
        report.update(passed=True, archive=str(output / 'complete.zip'), sha256=manifest['sha256'],
                      snapshot_at=manifest['snapshot_at'], tables=len(manifest['tables']),
                      runtime_files=manifest['runtime_files'], application_files=manifest['application_files'],
                      application_image=image, archive_members_verified=True)
        write_json(operations / 'latest-backup-success.json', report)
    except Exception as error:
        # Driver messages or command output can contain private data.
        report['error_type'] = type(error).__name__
    write_json(output / 'job.json', report)
    write_json(operations / 'latest-backup-attempt.json', report)
    return report


def evaluate(checks, previous, timestamp):
    failures = sorted(name for name, passed in checks.items() if not passed)
    report = {'at': timestamp, 'passed': not failures, 'failures': failures, 'checks': checks}
    events = []
    old = set(previous.get('failures', []))
    for status, names in (('opened', set(failures) - old), ('resolved', old - set(failures))):
        events.extend({'at': timestamp, 'check': name, 'status': status} for name in sorted(names))
    return report, events


def probe(root, operations):
    release = Path((root / 'prepared-release.txt').read_text().strip()).resolve()
    assert release.is_relative_to(root / 'releases')
    config = dict(line.split('=', 1) for line in (release / 'deployment.env').read_text().splitlines() if '=' in line)
    checks = {}
    try:
        with urllib.request.urlopen('http://127.0.0.1:18080/api/health/ready', timeout=8) as response:
            checks['application_ready'] = response.status == 200
    except Exception:
        checks['application_ready'] = False
    try:
        parsed = urlsplit(config['RKD_PUBLIC_ORIGIN'])
        result = subprocess.run(['docker', 'exec', 'tailscale', 'tailscale', 'serve', 'status', '--json'],
                                capture_output=True, text=True, check=True, timeout=10)
        serve = json.loads(result.stdout)
        checks['private_https_route'] = (parsed.scheme == 'https'
            and serve['TCP'][str(parsed.port)]['HTTPS']
            and serve['Web'][parsed.netloc]['Handlers']['/']['Proxy'] == 'http://127.0.0.1:18080'
            and not serve.get('AllowFunnel', {}).get(parsed.netloc, False))
    except Exception:
        checks['private_https_route'] = False
    for name, container in [('app_container', APP_CONTAINER), ('database_container', DB_CONTAINER)]:
        try:
            result = subprocess.run(['docker', 'inspect', container, '--format', '{{.State.Health.Status}}'],
                                    capture_output=True, text=True, timeout=10)
            checks[name] = result.returncode == 0 and result.stdout.strip() == 'healthy'
        except (OSError, subprocess.TimeoutExpired):
            checks[name] = False
    checks['disk_space'] = shutil.disk_usage(root).free >= 2 * 1024**3
    try:
        latest = json.loads((operations / 'latest-backup-success.json').read_text())
        age = (now() - datetime.fromisoformat(latest['snapshot_at'])).total_seconds()
        checks['backup_recent'] = latest['passed'] and 0 <= age <= 26 * 3600 and Path(latest['archive']).is_file()
        attempt = json.loads((operations / 'latest-backup-attempt.json').read_text())
        checks['latest_backup_attempt'] = attempt['passed']
    except (OSError, ValueError, KeyError):
        checks['backup_recent'] = checks['latest_backup_attempt'] = False
    status = operations / 'health.json'
    previous = json.loads(status.read_text()) if status.exists() else {}
    report, events = evaluate(checks, previous, now().isoformat())
    write_json(status, report)
    public = operations / 'public'
    public.mkdir(exist_ok=True, mode=0o755)
    public.chmod(0o755)
    for name in ('health.json', 'latest-backup-success.json'):
        source = operations / name
        if source.exists():
            write_json(public / name, json.loads(source.read_text()))
            (public / name).chmod(0o644)
    with (operations / 'events.jsonl').open('a', encoding='utf-8') as stream:
        for event in events:
            stream.write(json.dumps(event) + '\n')
            subprocess.run(['logger', '-t', 'rkd-ai-monitor', json.dumps(event)], check=False)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('backup', 'probe'))
    parser.add_argument('--root', type=Path, default=Path.home() / 'rkd-ai')
    args = parser.parse_args()
    root = args.root.resolve()
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise SystemExit('deployment root must belong to this operator')
    os.umask(0o077)
    release = Path((root / 'prepared-release.txt').read_text().strip()).resolve()
    if not release.is_relative_to(root / 'releases'):
        raise SystemExit('invalid prepared release')
    sys.path.insert(0, str(release / 'application/mvp'))
    operations = root / 'operations'
    operations.mkdir(mode=0o700, exist_ok=True)
    with (operations / (args.action + '.lock')).open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('job already running')
        report = backup(root, operations) if args.action == 'backup' else probe(root, operations)
    print(json.dumps(report))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
