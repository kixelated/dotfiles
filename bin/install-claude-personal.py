#!/usr/bin/env python3
"""Install the opt-in personal Claude gateway on an Ubuntu x86_64 host."""
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = '8.0.45'
SHA256 = 'e9e3a33a489d8a94ea9bd4b8eb4bb9286a978c3df11dc4c49f5ef393ef0fdc68'
URL = f'https://github.com/router-for-me/CLIProxyAPI/releases/download/v{VERSION}/CLIProxyAPI_{VERSION}_linux_amd64.tar.gz'


def main():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or Path('/etc/NIXOS').exists():
        raise SystemExit('This opt-in installer targets Ubuntu x86_64; NixOS work hosts are managed separately.')
    os.umask(0o077)
    home = Path.home()
    source = Path(__file__).resolve().parent.parent
    root = home / '.local/share/cliproxy-personal'
    config = home / '.config/cliproxy-personal'
    units = home / '.config/systemd/user'
    for path in (root, root/'auth', config, home/'.claude-personal', units, home/'.local/bin'):
        path.mkdir(parents=True, exist_ok=True)
    for path in (root, root/'auth', config, home/'.claude-personal'):
        path.chmod(0o700)
    binary = root / f'cli-proxy-api-{VERSION}'
    if not binary.exists():
        # Keep the temporary download inside the private installation directory.
        with tempfile.TemporaryDirectory(dir=root) as directory:
            archive = Path(directory) / 'release.tar.gz'
            with urllib.request.urlopen(URL, timeout=120) as response:
                archive.write_bytes(response.read())
            if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
                raise SystemExit('Release checksum mismatch; installation stopped.')
            with tarfile.open(archive) as tar:
                member = tar.getmember('cli-proxy-api')
                if not member.isfile():
                    raise SystemExit('Release binary is not a regular file.')
                staged = Path(directory) / 'cli-proxy-api'
                with tar.extractfile(member) as input_file, staged.open('xb') as output:
                    shutil.copyfileobj(input_file, output)
            staged.chmod(0o755)
            staged.replace(binary)
    link = root / 'cli-proxy-api'
    temporary = root / 'cli-proxy-api.next'
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(binary.name)
    temporary.replace(link)
    for name in ('client-key', 'management-key'):
        path = config / name
        if not path.exists():
            path.write_text(secrets.token_urlsafe(36) + '\n')
        path.chmod(0o600)
    path = config / 'config.yaml'
    if not path.exists():
        settings = {
            'config-version': 8,
            'server': {'host': '127.0.0.1', 'port': 8317, 'trusted-proxies': ['127.0.0.1', '::1']},
            'access': {'api-keys': [(config/'client-key').read_text().strip()]},
            'management': {'allow-remote': False, 'secret-key': (config/'management-key').read_text().strip(),
                           'disable-auto-update-panel': True},
            'oauth': {'auth-dir': str(root/'auth')},
            'upstream': {'claude': {'disable-claude-cloak-mode': True}},
            'routing': {'strategy': 'round-robin', 'session-affinity': True, 'session-affinity-ttl': '1h',
                        'retry': {'request-retry': 3, 'max-retry-interval': 30},
                        'cooldown': {'save-cooldown-status': True}},
            'observability': {'logs': {'request-log': False, 'logging-to-file': False, 'error-logs-max-files': 0},
                              'usage': {'usage-statistics-enabled': True}},
        }
        path.write_text(json.dumps(settings, indent=2) + '\n')
    path.chmod(0o600)
    for name in ('claude-personal', 'claude-personal-quota.py'):
        target = home / '.local/bin' / name
        if target.is_symlink():
            target.unlink()
        elif target.exists():
            raise SystemExit(f'Refusing to replace existing regular file: {target}')
        target.symlink_to(source/'bin'/name)
    for name in ('cliproxy-personal.service', 'claude-personal-quota.service', 'claude-personal-quota.timer'):
        shutil.copyfile(source/'systemd'/name, units/name)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'cliproxy-personal.service', 'claude-personal-quota.timer'], check=True)
    subprocess.run(['systemctl', '--user', 'restart', 'cliproxy-personal.service'], check=True)
    print('Personal gateway installed at http://127.0.0.1:8317; run claude-personal after signing in.')
    print('Check login persistence with: loginctl show-user "$USER" -p Linger')


if __name__ == '__main__':
    main()
