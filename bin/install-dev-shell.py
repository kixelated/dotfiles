#!/usr/bin/env python3
"""Install bin/dev-shell-hook as a user-level SessionStart hook.

Claude Code: merged into each profile's settings.json.
Codex: merged into $CODEX_HOME/hooks.json, trusted, and wired to commands
through BASH_ENV in $CODEX_HOME/config.toml.

Both merges are idempotent and preserve every other setting and hook.
"""

import json
import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import tempfile
import threading

CLAUDE_PROFILES = ('.claude', '.claude-personal', '.claude-api-credits')
BIN = Path(__file__).resolve().parent
HOOK = BIN / 'dev-shell-hook'
BASH_ENV = BIN.parent / 'codex' / 'bash-env.sh'
STATUS = 'Loading dev shell'


def command(mode):
    return f'{shlex.quote(str(HOOK))} {mode}'


def group(mode):
    hook = {'type': 'command', 'command': command(mode), 'statusMessage': STATUS}
    if mode == 'claude':
        # A first Nix build can take minutes; Codex already defaults to 600s.
        hook['timeout'] = 600
    return {'hooks': [hook]}


def is_ours(entry):
    return any('dev-shell-hook' in str(hook.get('command', '')) for hook in entry.get('hooks', []))


def merge(settings, mode):
    """Install the SessionStart group in `settings`; return whether it changed.

    An existing copy is replaced in place: Codex keys hook trust by position.
    """
    hooks = settings.setdefault('hooks', {})
    groups = hooks.setdefault('SessionStart', [])
    wanted = group(mode)
    positions = [index for index, entry in enumerate(groups) if is_ours(entry)]
    if len(positions) == 1 and groups[positions[0]] == wanted:
        return False
    index = positions[0] if positions else len(groups)
    groups[:] = [entry for entry in groups if not is_ours(entry)]
    groups.insert(index, wanted)
    return True


def update_json(path, mode):
    settings = json.loads(path.read_text()) if path.exists() else {}
    if not merge(settings, mode):
        return False
    write_json(path, settings)
    return True


def write_json(path, settings):
    """Atomically replace `path`, keeping its mode (0600 when new)."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    file_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(settings, output, indent=2)
            output.write('\n')
            os.fchmod(output.fileno(), file_mode)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f'Updated {path}')


class AppServer:
    """A minimal JSON-RPC client for `codex app-server` over stdio."""

    def __init__(self, codex_home):
        self.process = subprocess.Popen(
            ['codex', 'app-server'], cwd=Path.home(), env={**os.environ, 'CODEX_HOME': str(codex_home)},
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.watchdog = threading.Timer(120, self.process.kill)
        self.watchdog.start()
        self.next_id = 0
        self.request('initialize', {'clientInfo': {'name': 'dotfiles', 'version': '1'}})
        self.send({'method': 'initialized'})

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + '\n')
        self.process.stdin.flush()

    def request(self, method, params):
        self.next_id += 1
        self.send({'id': self.next_id, 'method': method, 'params': params})
        for line in self.process.stdout:
            message = json.loads(line)
            if message.get('id') != self.next_id:
                continue
            if 'error' in message:
                raise RuntimeError(f'codex app-server {method}: {message["error"]}')
            return message['result']
        raise RuntimeError(f'codex app-server exited before answering {method}')

    def close(self):
        self.watchdog.cancel()
        self.process.stdin.close()
        self.process.terminate()
        self.process.wait()
        self.process.stdout.close()


def install_codex(codex_home):
    """Trust the user hook and point BASH_ENV at the snapshot loader.

    Codex runs a user hook only after its declaration hash is recorded as
    trusted. Codex computes that hash itself, so the installer asks it.
    """
    update_json(codex_home / 'hooks.json', 'codex')
    link = codex_home / 'bash-env.sh'
    if not (link.is_symlink() and link.resolve() == BASH_ENV):
        link.unlink(missing_ok=True)
        link.symlink_to(BASH_ENV)
    if shutil.which('codex') is None:
        print('Skipping Codex hook trust: codex is not installed')
        return
    server = AppServer(codex_home)
    try:
        edits = []
        listed = server.request('hooks/list', {'cwds': [str(Path.home())]})
        hooks = [hook for entry in listed['data'] for hook in entry['hooks']
                 if hook['source'] == 'user' and hook.get('command') == command('codex')]
        if len(hooks) != 1:
            raise RuntimeError(f'expected one dev shell hook in Codex, found {len(hooks)}')
        if hooks[0]['trustStatus'] != 'trusted':
            edits.append({'keyPath': 'hooks.state', 'mergeStrategy': 'upsert',
                          'value': {hooks[0]['key']: {'trusted_hash': hooks[0]['currentHash']}}})
        layers = server.request('config/read', {'includeLayers': True})['layers']
        user = next((layer['config'] for layer in layers if layer['name']['type'] == 'user'), {})
        policy = (user.get('shell_environment_policy') or {}).get('set') or {}
        if policy.get('BASH_ENV') != str(link):
            edits.append({'keyPath': 'shell_environment_policy.set', 'mergeStrategy': 'upsert',
                          'value': {'BASH_ENV': str(link)}})
        if edits:
            result = server.request('config/batchWrite', {'edits': edits})
            print(f'Updated {result["filePath"]}')
    finally:
        server.close()


def main():
    home = Path.home()
    for profile in CLAUDE_PROFILES:
        update_json(home / profile / 'settings.json', 'claude')
    install_codex(Path(os.environ.get('CODEX_HOME') or home / '.codex'))


if __name__ == '__main__':
    main()
