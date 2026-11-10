"""Verify and stage a NAS release as the SSH user. Docker access is not needed.

This writes only beneath the explicitly selected new deployment directory.
Passwords are generated locally, retained in protected files and never printed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import secrets
import stat
import zipfile


def prepare(archive_path, deployment_root):
    root = Path(deployment_root).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.is_symlink() or root.stat().st_uid != os.getuid():
        raise RuntimeError("deployment directory must belong to this user")
    os.chmod(root,0o700)
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("deployment-release.json"))
        release = manifest['release']
        if not release or any(char not in "0123456789abcdefghijklmnopqrstuvwxyz-" for char in release):
            raise RuntimeError("unsafe release id")
        target = root / "releases" / release
        if target.exists():
            raise RuntimeError("release destination already exists")
        expected = manifest['files']
        if len(archive.namelist()) != len(set(archive.namelist())) or set(archive.namelist()) != {*expected,"deployment-release.json"}:
            raise RuntimeError("archive inventory mismatch")
        total = 0
        for entry in archive.infolist():
            name = entry.filename
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name or ":" in name or stat.S_ISLNK(entry.external_attr >> 16):
                raise RuntimeError("unsafe archive path")
            total += entry.file_size
            if total > 500*1024*1024:
                raise RuntimeError("deployment archive exceeds size limit")
            content = archive.read(name)
            if name in expected and (len(content) != expected[name]['size_bytes'] or hashlib.sha256(content).hexdigest() != expected[name]['sha256']):
                raise RuntimeError("deployment byte verification failed")
        target.mkdir(parents=True,mode=0o700)
        for name in archive.namelist():
            path = target / name
            path.parent.mkdir(parents=True,exist_ok=True)
            with path.open("xb") as output:
                output.write(archive.read(name))
    secret_root = root / "secrets"
    secret_root.mkdir(mode=0o700,exist_ok=True)
    os.chmod(secret_root,0o700)
    for name in ("owner_password","app_password"):
        path = secret_root / name
        if not path.exists():
            with path.open("x") as output:
                output.write(secrets.token_urlsafe(48))
        if path.is_symlink() or path.stat().st_uid != os.getuid():
            raise RuntimeError("invalid secret file")
        # Compose file secrets are read-only bind mounts. Parent directories
        # protect them on the host; the non-root application must read its file.
        os.chmod(path,0o444)
    env = target / "deployment.env"
    env.write_text(f"RKD_RELEASE={release}\nRKD_DEPLOY_ROOT={root}\nRKD_PUBLIC_ORIGIN=http://127.0.0.1:18080\n",encoding="utf-8")
    (root / "prepared-release.txt").write_text(str(target),encoding="utf-8")
    print(json.dumps({"staged":True,"release":release,"directory":str(target),"files_verified":len(expected),
                      "runtime_files":manifest['runtime_files'],"docker_started":False,"network_listener_opened":False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("archive",type=Path)
    parser.add_argument("deployment_root",type=Path)
    args = parser.parse_args()
    prepare(args.archive,args.deployment_root)
