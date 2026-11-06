#!/usr/bin/env python3
"""Install `claude-proxy`, which runs Claude Code through a CLIProxyAPI subscription gateway.

Without --gateway, this host runs the gateway (Ubuntu x86_64 only). With
--gateway HOST, this host uses HOST's gateway over the tailnet instead.
Bare `claude` is left alone either way.
"""
import argparse
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

VERSION = '8.0.47'
SHA256 = '2b5111dc6a0dfe0d607457787f794330d1b477bc9daa6337c26b0cd032a7827e'
URL = f'https://github.com/router-for-me/CLIProxyAPI/releases/download/v{VERSION}/CLIProxyAPI_{VERSION}_linux_amd64.tar.gz'
PORT = 8317
T3_INSTANCE = 'claude_proxy'


def private_dir(path):
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)


def write_private(path, text):
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(text)
    temporary.chmod(0o600)
    temporary.replace(path)


def link(path, target):
    """Point path at target, refusing to replace anything but a symlink."""
    if path.is_symlink():
        if path.readlink() == target:
            return
        path.unlink()
    elif path.exists():
        raise SystemExit(f'Refusing to replace existing file: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target)


def install_client(home, source):
    """Install the launcher and its Claude profile, shared by gateway and client hosts."""
    link(home / '.local/bin/claude-proxy', source / 'bin/claude-proxy')
    profile = home / '.claude-proxy'
    private_dir(profile)
    # Share instructions and skills with the stock profile, which `install` links to this checkout.
    for name in ('CLAUDE.md', 'skills'):
        link(profile / name, home / '.claude' / name)


def install_gateway(home, source):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64' or Path('/etc/NIXOS').exists():
        raise SystemExit('The gateway targets Ubuntu x86_64; on other hosts pass --gateway HOST.')
    root = home / '.local/share/cliproxy-proxy'
    config = home / '.config/cliproxy-proxy'
    units = home / '.config/systemd/user'
    for path in (root, root / 'auth', config):
        private_dir(path)
    units.mkdir(parents=True, exist_ok=True)
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
    current = root / 'cli-proxy-api'
    temporary = root / 'cli-proxy-api.next'
    if temporary.is_symlink():
        temporary.unlink()
    temporary.symlink_to(binary.name)
    temporary.replace(current)
    for name in ('client-key', 'management-key'):
        path = config / name
        if not path.exists():
            write_private(path, secrets.token_urlsafe(36) + '\n')
    # This host serves the gateway itself, on loopback.
    (config / 'base-url').unlink(missing_ok=True)
    path = config / 'config.yaml'
    if not path.exists():
        settings = {
            'config-version': 8,
            'server': {'host': '127.0.0.1', 'port': PORT, 'trusted-proxies': ['127.0.0.1', '::1']},
            'access': {'api-keys': [(config / 'client-key').read_text().strip()]},
            'management': {'allow-remote': False, 'secret-key': (config / 'management-key').read_text().strip(),
                           'disable-auto-update-panel': True},
            'oauth': {'auth-dir': str(root / 'auth')},
            'upstream': {'claude': {'disable-claude-cloak-mode': True}},
            'routing': {'strategy': 'round-robin', 'session-affinity': True, 'session-affinity-ttl': '1h',
                        'retry': {'request-retry': 3, 'max-retry-interval': 30},
                        'cooldown': {'save-cooldown-status': True}},
            'observability': {'logs': {'request-log': False, 'logging-to-file': False, 'error-logs-max-files': 0},
                              'usage': {'usage-statistics-enabled': True}},
        }
        write_private(path, json.dumps(settings, indent=2) + '\n')
    link(home / '.local/bin/claude-proxy-quota.py', source / 'bin/claude-proxy-quota.py')
    for name in ('cliproxy-proxy.service', 'claude-proxy-quota.service', 'claude-proxy-quota.timer'):
        shutil.copyfile(source / 'systemd' / name, units / name)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', '--user', 'enable', '--now', 'cliproxy-proxy.service', 'claude-proxy-quota.timer'], check=True)
    subprocess.run(['systemctl', '--user', 'restart', 'cliproxy-proxy.service'], check=True)
    print(f'Gateway installed at http://127.0.0.1:{PORT}.')
    print(f'Share it on the tailnet with: sudo tailscale serve --bg --tcp {PORT} tcp://127.0.0.1:{PORT}')


def use_gateway(home, host, read_key):
    """Point this host's launcher at another host's gateway."""
    config = home / '.config/cliproxy-proxy'
    private_dir(config)
    key = read_key(host).strip()
    if not key:
        raise SystemExit(f'{host} returned an empty gateway key; install the gateway there first.')
    write_private(config / 'client-key', key + '\n')
    write_private(config / 'base-url', f'http://{host}:{PORT}\n')
    print(f'claude-proxy uses the gateway at http://{host}:{PORT}.')


def ssh_key(host):
    # No stdin: ssh would otherwise swallow the rest of a script piped into a shell.
    return subprocess.run(['ssh', host, 'cat .config/cliproxy-proxy/client-key'], stdin=subprocess.DEVNULL,
                          check=True, capture_output=True, text=True).stdout


def configure_t3(home):
    """Add the Claude Proxy provider; the launcher supplies routing, so it needs no environment."""
    path = home / '.t3/userdata/settings.json'
    if not path.exists():
        print(f'{path} not found; skipping T3.')
        return
    original = path.read_text()
    settings = json.loads(original)
    settings.setdefault('providerInstances', {})[T3_INSTANCE] = {
        'driver': 'claudeAgent',
        'displayName': 'Claude Proxy',
        'enabled': True,
        'config': {'binaryPath': str(home / '.local/bin/claude-proxy'), 'homePath': str(home / '.claude-proxy')},
    }
    temporary = path.with_name('settings.claude-proxy.new')
    temporary.write_text(json.dumps(settings, indent=2) + '\n')
    temporary.chmod(path.stat().st_mode & 0o777)
    if path.read_text() != original:
        temporary.unlink()
        raise SystemExit('T3 settings changed concurrently; rerun.')
    temporary.replace(path)
    print('T3 provider "Claude Proxy" configured.')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gateway', metavar='HOST', help="use HOST's gateway (over ssh and the tailnet) instead of running one")
    parser.add_argument('--configure-t3', action='store_true', help='add the "Claude Proxy" provider to T3 on this host')
    args = parser.parse_args()
    os.umask(0o077)
    home = Path.home()
    source = Path(__file__).resolve().parent.parent
    install_client(home, source)
    if args.gateway:
        use_gateway(home, args.gateway, ssh_key)
    else:
        install_gateway(home, source)
    if args.configure_t3:
        configure_t3(home)


if __name__ == '__main__':
    main()
