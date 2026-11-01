#!/usr/bin/env python3
"""Make the Personal launcher the host default without changing explicit providers."""
from pathlib import Path


def install(home, source):
    cli = home / '.local/bin/claude'
    native = home / '.local/bin/claude-native'
    launcher = source / 'bin/claude-personal'
    if not cli.is_symlink():
        raise SystemExit(f'Expected the official Claude Code symlink at {cli}; refusing to replace a regular file.')
    current = cli.resolve(strict=True)
    if current == launcher:
        if not native.exists() or native.resolve() == launcher:
            raise SystemExit('Default launcher has no official Claude binary; reinstall Claude Code first.')
        return
    if not (home / '.config/cliproxy-personal/client-key').is_file():
        raise SystemExit('Install the Personal gateway before making it the default.')
    if native.exists() and not native.is_symlink():
        raise SystemExit(f'Refusing to replace a regular file: {native}')
    for path, target in ((native, current), (cli, launcher)):
        temporary = path.with_name(path.name + '.next')
        temporary.symlink_to(target)
        temporary.replace(path)
    print(f'{cli} defaults to Personal; official binary preserved at {native}.')


if __name__ == '__main__':
    install(Path.home(), Path(__file__).resolve().parent.parent)
