"""Interactive personal administrator setup; never receives a password argument."""
from pathlib import Path
import subprocess


def main():
    root=Path.home()/"rkd-ai"
    release=Path((root/'prepared-release.txt').read_text().strip()).resolve()
    if not release.is_relative_to((root/'releases').resolve()):
        raise SystemExit('invalid prepared release path')
    compose=['docker','compose','--env-file',str(release/'deployment.env'),'-f',str(release/'application/scripts/deploy/compose.yaml')]
    profile=release/'application/scripts/deploy/compose.nas-cache.yaml'
    if profile.exists():
        compose.extend(['-f',str(profile)])
    result = subprocess.run([*compose,'exec','app','python','scripts/deploy/container_entry.py','accounts'])
    if result.returncode:
        raise SystemExit('账号设置未完成，请按上方提示修正后重新运行；密码需 8–128 个字符。')


if __name__=='__main__':
    main()
