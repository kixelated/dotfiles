#!/usr/bin/env python3
"""Install bin/dev-shell-hook as a user-level SessionStart hook.

Claude Code: merged into each profile's settings.json.
Codex: merged into $CODEX_HOME/hooks.json, trusted, and wired to commands
through BASH_ENV in $CODEX_HOME/config.toml.
Grok: merged into $GROK_HOME/hooks/dev-shell.json, with session.load_envrc and
BASH_ENV in $GROK_HOME/config.toml. Grok records an error for statusMessage,
so that hook omits it.

Each merge is idempotent and preserves every other setting and hook.
"""

import json
import os
from pathlib import Path
import re
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
GROK_BASH_ENV = BIN.parent / 'grok' / 'bash-env.sh'
STATUS = 'Loading dev shell'
ASSIGNMENT = re.compile(r'\s*([A-Za-z0-9_-]+)\s*=')


def command(mode):
    return f'{shlex.quote(str(HOOK))} {mode}'


def group(mode):
    hook = {'type': 'command', 'command': command(mode)}
    # Grok records a load error for statusMessage and still runs the hook.
    if mode != 'grok':
        hook['statusMessage'] = STATUS
    if mode in ('claude', 'grok'):
        # A first Nix build can take minutes; Codex already defaults to 600s.
        # Grok's observe hooks default to 5s, which kills the load.
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


def write_text(path, text):
    """Atomically replace `path`, keeping its mode (0600 when new)."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    file_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
            os.fchmod(output.fileno(), file_mode)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print(f'Updated {path}')


def write_json(path, settings):
    write_text(path, json.dumps(settings, indent=2) + '\n')


def table_name(line):
    """The table this line opens. Array tables return their raw header so keys under them are left alone."""
    stripped = line.split('#', 1)[0].strip()
    if len(stripped) < 3 or stripped[0] != '[' or stripped[-1] != ']':
        return None
    if stripped.startswith('[['):
        return stripped
    return stripped[1:-1].strip()


def assignment_key(line):
    stripped = line.strip()
    if not stripped or stripped.startswith('#'):
        return None
    match = ASSIGNMENT.match(stripped)
    return match.group(1) if match else None


def set_assignments(text, updates):
    """Set `updates` (`table` to `{key: toml literal}`) and return the new text.

    Existing keys are replaced in place. Missing keys are inserted at the end
    of their table. Missing tables are appended. A text that already has the
    values is returned unchanged.
    """
    pending = {table: dict(keys) for table, keys in updates.items()}
    lines = text.splitlines(keepends=True)
    out = []
    current = None

    def flush():
        keys = pending.pop(current, None)
        if not keys:
            return
        if out and not out[-1].endswith('\n'):
            out[-1] += '\n'
        for key, literal in keys.items():
            out.append(f'{key} = {literal}\n')

    for line in lines:
        header = table_name(line)
        if header is not None:
            flush()
            current = header
            out.append(line)
            continue
        key = assignment_key(line)
        if current in pending and key in pending[current]:
            newline = '\n' if line.endswith('\n') or not line else '\n'
            out.append(f'{key} = {pending[current].pop(key)}{newline}')
            if not pending[current]:
                del pending[current]
            continue
        out.append(line)
    flush()
    for table, keys in pending.items():
        if out and not out[-1].endswith('\n'):
            out[-1] += '\n'
        if out and out[-1].strip():
            out.append('\n')
        out.append(f'[{table}]\n')
        for key, literal in keys.items():
            out.append(f'{key} = {literal}\n')
    updated = ''.join(out)
    if text and not text.endswith('\n') and updated.endswith('\n') and updated[:-1] == text:
        return text
    return updated


def update_grok_config(path, bash_env):
    original = path.read_text() if path.exists() else ''
    updated = set_assignments(original, {
        'session': {'load_envrc': 'true'},
        'shell_environment_policy.set': {'BASH_ENV': json.dumps(bash_env)},
    })
    if updated == original:
        return False
    write_text(path, updated)
    return True


def install_grok(grok_home):
    """Point Grok's bash at the dev shell snapshot and load `.envrc` natively.

    `session.load_envrc` makes Grok run `direnv export` for an allowed
    checkout. The hook allows a fresh worktree when its dev shell files match
    the remote default branch, and BASH_ENV loads the snapshot the hook wrote.
    """
    changed = update_json(grok_home / 'hooks' / 'dev-shell.json', 'grok')
    link = grok_home / 'bash-env.sh'
    if not (link.is_symlink() and link.resolve() == GROK_BASH_ENV):
        link.unlink(missing_ok=True)
        link.symlink_to(GROK_BASH_ENV)
        changed = True
    return update_grok_config(grok_home / 'config.toml', str(link)) or changed


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
    install_grok(Path(os.environ.get('GROK_HOME') or home / '.grok'))


if __name__ == '__main__':
    main()
