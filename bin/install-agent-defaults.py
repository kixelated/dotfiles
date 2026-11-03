#!/usr/bin/env python3
"""Merge the default model and reasoning effort into Claude Code and Codex.

Claude Code: `effortLevel` in each profile's settings.json.
Codex: `model` and `model_reasoning_effort` in $CODEX_HOME/config.toml,
written by Codex itself so trust hashes and local settings survive.

Both merges are idempotent and preserve every other setting.
"""

import importlib.util
import json
import os
from pathlib import Path
import shutil

CLAUDE = {'effortLevel': 'high'}
CODEX = {'model': 'gpt-6.1-sol', 'model_reasoning_effort': 'xhigh'}

# Reuse the dev shell installer's profile list, atomic writer, and app-server client.
_spec = importlib.util.spec_from_file_location(
    'install_dev_shell', Path(__file__).resolve().parent / 'install-dev-shell.py')
dev_shell = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dev_shell)


def install_claude(path):
    """Merge CLAUDE into the settings at `path`; return whether it changed."""
    settings = json.loads(path.read_text()) if path.exists() else {}
    if all(settings.get(key) == value for key, value in CLAUDE.items()):
        return False
    settings.update(CLAUDE)
    dev_shell.write_json(path, settings)
    return True


def install_codex(codex_home):
    """Merge CODEX into config.toml; return whether it changed."""
    if shutil.which('codex') is None:
        print('Skipping Codex defaults: codex is not installed')
        return False
    server = dev_shell.AppServer(codex_home)
    try:
        layers = server.request('config/read', {'includeLayers': True})['layers']
        user = next((layer['config'] for layer in layers if layer['name']['type'] == 'user'), {})
        edits = [{'keyPath': key, 'mergeStrategy': 'replace', 'value': value}
                 for key, value in CODEX.items() if user.get(key) != value]
        if not edits:
            return False
        result = server.request('config/batchWrite', {'edits': edits})
        print(f'Updated {result["filePath"]}')
        return True
    finally:
        server.close()


def main():
    home = Path.home()
    for profile in dev_shell.CLAUDE_PROFILES:
        install_claude(home / profile / 'settings.json')
    install_codex(Path(os.environ.get('CODEX_HOME') or home / '.codex'))


if __name__ == '__main__':
    main()
