"""Start only the reviewed, isolated RKD Compose project; never edits NAS services."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release_directory",type=Path)
    args = parser.parse_args()
    release = args.release_directory.resolve()
    manifest = json.loads((release / "deployment-release.json").read_text())
    for name, expected in manifest['files'].items():
        path = (release / name).resolve()
        if not path.is_relative_to(release) or not path.is_file():
            raise SystemExit("staged release contains an unsafe or missing file")
        data = path.read_bytes()
        if len(data) != expected['size_bytes'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
            raise SystemExit("staged release bytes differ from the reviewed manifest")
    compose = ["docker","compose","--env-file",str(release / "deployment.env"),"-f",str(release / "application/scripts/deploy/compose.yaml")]
    subprocess.run([*compose,"config","--quiet"],check=True)
    # A failed access check stops before builds, network listeners or volumes.
    subprocess.run(["docker","info","--format","{{.ServerVersion}}"],check=True)
    existing = subprocess.run([*compose,"ps","--all","--quiet"],check=True,capture_output=True,text=True)
    if existing.stdout.strip():
        raise SystemExit("RKD Compose project already exists; review it before upgrading")
    for port in (15432,18080):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1",port))
            except OSError:
                raise SystemExit("required isolated loopback port is already in use")
    subprocess.run([*compose,"build","app"],check=True)
    subprocess.run([*compose,"up","-d","database"],check=True)
    subprocess.run([*compose,"run","--rm","initialize"],check=True)
    subprocess.run([*compose,"up","-d","app"],check=True)
    healthy = False
    for _ in range(30):
        try:
            with urllib.request.urlopen("http://127.0.0.1:18080/api/health/ready",timeout=3) as response:
                healthy = response.status == 200
                if healthy:
                    break
        except OSError:
            time.sleep(1)
    if not healthy:
        raise SystemExit("new application is not ready; candidate retained for inspection")
    report = {"release":manifest['release'],"database":"127.0.0.1:15432","application":"127.0.0.1:18080",
              "private_preview_only":True,"https_verified":False,"authoritative_cutover":False,
              "next":"Set a personal administrator via interactive container_entry.py accounts; verify Tailscale HTTPS before team access"}
    (release / "deployment-report.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
