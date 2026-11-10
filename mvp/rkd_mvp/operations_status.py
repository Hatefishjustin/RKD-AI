"""Read a public, sanitized host-maintenance projection. Never expose paths/secrets."""
from datetime import datetime, timezone
import json
from pathlib import Path


def read_status(directory):
    if not directory:
        return {'configured': False}
    try:
        root = Path(directory)
        health = json.loads((root / 'health.json').read_text())
        backup = json.loads((root / 'latest-backup-success.json').read_text())
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(health['at'])).total_seconds()
        stale = not 0 <= age <= 180
        checks = {key: health.get('checks', {}).get(key) is True for key in
                  ('application_ready', 'private_https_route', 'app_container', 'database_container',
                   'disk_space', 'backup_recent', 'latest_backup_attempt')}
        return {'configured': True, 'available': True, 'passed': all(checks.values()) and not stale,
                'stale': stale, 'checked_at': health['at'], 'checks': checks,
                'backup_at': backup['snapshot_at'], 'external_notifications': False}
    except (OSError, ValueError, KeyError, TypeError):
        return {'configured': True, 'available': False, 'passed': False}
