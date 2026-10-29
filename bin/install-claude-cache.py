#!/usr/bin/env python3
"""Merge the cache policy into each Claude Code profile's user settings."""

import json
import os
from pathlib import Path
import stat
import tempfile


def main():
    for profile in ('.claude', '.claude-personal', '.claude-api-credits'):
        path = Path.home() / profile / 'settings.json'
        settings = json.loads(path.read_text()) if path.exists() else {}
        policy = {
            'promptCacheTtl': '1h',
            'subagentPromptCacheTtl': '5m' if profile == '.claude-api-credits' else '1h',
        }
        if all(settings.get(key) == value for key, value in policy.items()):
            continue
        settings.update(policy)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o600
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
                temporary = Path(output.name)
                json.dump(settings, output, indent=2)
                output.write('\n')
                os.fchmod(output.fileno(), mode)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        print(f'Updated {path}')


if __name__ == '__main__':
    main()
