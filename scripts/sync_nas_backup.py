"""Copy the latest successful NAS archive over existing SSH trust; verify before publication."""
from datetime import datetime, timezone
import time
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'mvp'))
from rkd_mvp.postgres_backup import _extract


def _sha256_file(path,chunk=1024*1024):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(chunk),b''):digest.update(block)
    return digest.hexdigest()


def main():
    destination=ROOT/'var/backups/nas'
    destination.mkdir(parents=True,exist_ok=True)
    lock=(destination/'sync.lock').open('a+b')
    if os.name=='nt':
        import msvcrt
        lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
        msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
    else:
        import fcntl
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    report={'passed':False,'at':datetime.now(timezone.utc).isoformat(),'live_runtime_replaced':False}
    def save(name,data):
        temporary=destination/(name+'.tmp-'+uuid.uuid4().hex)
        temporary.write_text(json.dumps(data,indent=2),encoding='utf-8');temporary.replace(destination/name)
    try:
        key=Path.home()/'.ssh/id_ed25519_nas'
        ssh=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=15','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3','-i',str(key),'Justin@100.73.240.73']
        latest=json.loads(subprocess.check_output([*ssh,'cat /home/Justin/rkd-ai/operations/latest-backup-success.json'],timeout=30))
        archive=latest.get('archive','');digest=latest.get('sha256','')
        if not latest.get('passed') or not re.fullmatch(r'/home/Justin/rkd-ai/backups/online-\d{8}T\d{6}-[a-f0-9]+/complete.zip',archive) or not re.fullmatch('[a-f0-9]{64}',digest):
            raise RuntimeError('Invalid NAS success metadata')
        folder=destination/archive.split('/')[-2];folder.mkdir(exist_ok=True)
        target=folder/'complete.zip'
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:raise RuntimeError('Existing off-NAS archive differs; preserved for inspection')
            verified=json.loads((folder/'verified.json').read_text(encoding='utf-8'))
            if verified['sha256']!=digest or not verified['passed']:raise RuntimeError('Missing verification receipt')
            report.update(verified,at=report['at'],already_present=True)
        else:
            if shutil.disk_usage(destination).free<2*1024**3:raise RuntimeError('Less than 2 GiB free; no existing backup deleted')
            partial=folder/('complete.partial-'+uuid.uuid4().hex)
            size=int(subprocess.check_output([*ssh,'stat -c %s '+archive],timeout=30))
            # Single SSH session per attempt: the remote side streams the archive with `cat`
            # and the local side writes those bytes straight to disk. This replaces the old
            # 256 KiB-per-block loop, which started one ssh.exe per block and flooded the
            # desktop with console windows.
            transfer_timeout=max(120,60+30*(size//1024**2))
            for attempt in range(3):
                try:
                    with partial.open('wb') as stream:
                        subprocess.run([*ssh,'cat '+archive],stdout=stream,stderr=subprocess.PIPE,timeout=transfer_timeout,check=True)
                    if partial.stat().st_size!=size:raise RuntimeError('Incomplete transfer')
                    break
                except (subprocess.SubprocessError,RuntimeError,OSError):
                    if attempt==2:raise
                    time.sleep(2)
            if _sha256_file(partial)!=digest:raise RuntimeError('Transferred archive hash differs')
            stage=folder/('verified-package-'+uuid.uuid4().hex[:8])
            manifest=_extract(partial,stage)
            partial.rename(target)
            report.update(passed=True,sha256=digest,archive=str(target),source_archive=archive,snapshot_at=latest['snapshot_at'],tables=len(manifest['tables']),runtime_files=manifest['runtime_files'],application_files=manifest['application_files'],members_verified=True)
            save(str((folder/'verified.json').relative_to(destination)),report)
        save('latest-success.json',report);save('latest-attempt.json',report)
        print(json.dumps(report))
    except Exception as error:
        # Do not log SSH stderr or connection strings.
        report['error_type']=type(error).__name__;save('latest-attempt.json',report)
        print(json.dumps(report));raise SystemExit(1) from None
    finally:lock.close()


if __name__=='__main__':main()
