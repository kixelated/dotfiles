#!/usr/bin/env python3
"""Install a separate loopback-only Claude API-key gateway on the desktop."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request


def gateway_config(imported, state, management_key):
    groups = imported.get('api-keys', {}).get('claude', [])
    if not groups or not any(key.get('api-key') for group in groups for key in group.get('keys', [])):
        raise ValueError('Import must contain at least one Claude API key')
    client_keys = imported.get('access', {}).get('api-keys', [])
    if not client_keys or not all(isinstance(key, str) and key for key in client_keys):
        raise ValueError('Import must contain client access keys')
    return {
        'config-version': 8,
        'server': {'host': '127.0.0.1', 'port': 8318, 'trusted-proxies': ['127.0.0.1', '::1']},
        'access': {'api-keys': client_keys},
        'management': {'allow-remote': False, 'secret-key': management_key,
                       'disable-auto-update-panel': True},
        'oauth': {'auth-dir': str(state / 'auth')},
        'api-keys': {'claude': deepcopy(groups)},
        'upstream': deepcopy(imported.get('upstream', {})),
        'routing': deepcopy(imported.get('routing', {'strategy': 'round-robin'})),
        'observability': {'logs': {'request-log': False, 'logging-to-file': False},
                          'usage': {'usage-statistics-enabled': True}},
    }


def update_t3(path):
    original = path.read_bytes()
    settings = json.loads(original)
    instance = settings['providerInstances']['claude_api_credits']
    environment = instance['environment']
    endpoint = next(item for item in environment if item['name'] == 'ANTHROPIC_BASE_URL')
    if endpoint['value'] == 'http://127.0.0.1:8318':
        return
    backup = path.parent / 'settings.before-local-claude-api.json'
    if not backup.exists():
        with backup.open('xb') as output:
            output.write(original)
        backup.chmod(0o600)
    endpoint['value'] = 'http://127.0.0.1:8318'
    # Preserve provider IDs, secret references, profiles, and every other setting.
    temporary = path.with_name('settings.claude-api.new')
    temporary.write_text(json.dumps(settings, indent=2) + '\n')
    temporary.chmod(0o600)
    if path.read_bytes() != original:
        temporary.unlink()
        raise RuntimeError('T3 settings changed concurrently; retry the endpoint update')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--import-config', metavar='JSON', help='Initial v8 JSON config, or - for stdin; contains secrets')
    parser.add_argument('--binary', type=Path, default=Path.home() / '.local/share/cliproxy-personal/cli-proxy-api')
    parser.add_argument('--configure-t3', action='store_true', help='Switch only the existing Claude API endpoint after health checks')
    args = parser.parse_args()
    if sys.platform != 'linux' or Path('/etc/NIXOS').exists():
        parser.error('This opt-in installer targets the Linux desktop; NixOS is managed separately')
    binary = args.binary.expanduser().resolve(strict=True)
    if not os.access(binary, os.X_OK):
        parser.error('Gateway binary must be executable')
    os.umask(0o077)
    home = Path.home()
    source = Path(__file__).resolve().parent.parent
    config = home / '.config/cliproxy-api'
    state = home / '.local/share/cliproxy-api'
    path = config / 'config.yaml'
    if args.import_config and path.exists():
        parser.error('Gateway already configured; rerun without --import-config to preserve its keys')
    if not path.exists() and not args.import_config:
        parser.error('First install requires --import-config')
    imported = None
    if args.import_config:
        imported = json.load(sys.stdin) if args.import_config == '-' else json.loads(Path(args.import_config).read_text())
        # Validate before creating any files.
        gateway_config(imported, state, 'validation-only')
    units = home / '.config/systemd/user'
    for directory in (config, state, state / 'auth', units, home / '.local/bin'):
        directory.mkdir(parents=True, exist_ok=True)
    for directory in (config, state, state / 'auth'):
        directory.chmod(0o700)
    if any((state / 'auth').glob('*.json')):
        parser.error('API gateway must not contain OAuth credentials; subscriptions belong in Personal')
    management = config / 'management-key'
    if not management.exists():
        management.write_text(secrets.token_urlsafe(36) + '\n')
    management.chmod(0o600)
    if imported is not None:
        settings = gateway_config(imported, state, management.read_text().strip())
        path.write_text(json.dumps(settings, indent=2) + '\n')
        (config / 'client-key').write_text(settings['access']['api-keys'][0] + '\n')
        (config / 'client-key').chmod(0o600)
    path.chmod(0o600)
    link = state / 'cli-proxy-api'
    if link.exists() and not link.is_symlink():
        parser.error('Refusing to replace a regular gateway binary')
    temporary = state / 'cli-proxy-api.next'
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(binary)
    temporary.replace(link)
    for name in ('claude-api-status.py',):
        target = home / '.local/bin' / name
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            parser.error(f'Refusing to replace existing file: {target}')
        target.symlink_to(source / 'bin' / name)
    shutil.copyfile(source / 'systemd/cliproxy-api.service', units / 'cliproxy-api.service')
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'cliproxy-api.service'], check=True)
    # The unit may already be running when refreshing its config/binary.
    if imported is None:
        subprocess.run(['systemctl', '--user', 'restart', 'cliproxy-api.service'], check=True)
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(20):
        try:
            request = urllib.request.Request('http://127.0.0.1:8318/v1/models', headers={
                'Authorization': 'Bearer ' + (config / 'client-key').read_text().strip()})
            with http.open(request, timeout=2) as response:
                models = json.load(response)['data']
            if not models:
                raise RuntimeError('API gateway returned no models')
            break
        except urllib.error.HTTPError:
            raise
        except OSError:
            if attempt == 19:
                raise
            time.sleep(0.25)
    if args.configure_t3:
        update_t3(home / '.t3/userdata/settings.json')
    print('Claude API gateway ready at http://127.0.0.1:8318; Personal remains on port 8317.')
    print('Status: claude-api-status.py')


if __name__ == '__main__':
    main()
