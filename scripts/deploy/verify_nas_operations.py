"""Fault/restart check for these two RKD containers only, before personal use."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
import urllib.request


def inspect(name):
    return json.loads(subprocess.check_output(['docker','inspect','--format','{{json .State}}',name]))


def ready():
    for _ in range(50):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18080/api/health/ready',timeout=2) as response:
                if response.status==200: return
        except OSError: pass
        time.sleep(.5)
    raise RuntimeError('RKD did not become ready')


def main():
    root=Path.home()/'rkd-ai'
    ready()
    before=inspect('rkd-ai-app-1')
    # docker kill is an operator stop and suppresses Docker restart policy.
    # Signal the server from inside instead, exercising an unexpected exit.
    subprocess.run(['docker','exec','rkd-ai-app-1','python','-c',
                    'import os,signal; os.kill(1,signal.SIGTERM)'],check=True,capture_output=True)
    for _ in range(60):
        state=inspect('rkd-ai-app-1')
        if state['Running'] and before['StartedAt']!=state['StartedAt']:
            break
        time.sleep(.5)
    else:
        raise RuntimeError('application process did not automatically restart')
    ready()
    after=inspect('rkd-ai-app-1')
    assert before['StartedAt']!=after['StartedAt']
    restarts=int(subprocess.check_output(['docker','inspect','--format','{{.RestartCount}}','rkd-ai-app-1']))
    assert restarts>=1
    subprocess.run(['docker','restart','rkd-ai-database-1'],check=True,capture_output=True)
    ready()
    request=urllib.request.Request('http://127.0.0.1:18080/api/v1/auth/config',
                                  headers={'Host':'fnos-nas.tailcca6f8.ts.net:9443'})
    with urllib.request.urlopen(request) as response:
        auth=json.load(response)
    assert auth['mode']=='accounts' and not auth['initialized']
    report={'passed':True,'at':datetime.now(timezone.utc).isoformat(),'application_process_exit_auto_restart':True,
            'application_restart_count':restarts,'database_restart_ready':True,'accounts_required':True,
            'personal_account_initialized':False}
    (root/'qa/operations.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__=='__main__':
    main()
