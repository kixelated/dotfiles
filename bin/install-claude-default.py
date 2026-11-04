#!/usr/bin/env python3
"""Make the Personal launcher the host default without changing explicit providers."""
from pathlib import Path
import tempfile


def install(home, source):
    cli = home / '.local/bin/claude'
    native = home / '.local/bin/claude-native'
    personal = home / '.local/bin/claude-personal'
    launcher = source / 'bin/claude-personal'
    installed = home / '.local/lib/claude-personal'
    if not cli.is_symlink():
        raise SystemExit(f'Expected the official Claude Code symlink at {cli}; refusing to replace a regular file.')
    if personal.exists() and not personal.is_symlink():
        raise SystemExit(f'Refusing to replace a regular file: {personal}')
    if native.exists() and not native.is_symlink():
        raise SystemExit(f'Refusing to replace a regular file: {native}')
    current = cli.resolve()
    wrappers = {launcher.resolve(), installed.resolve(), personal.resolve()}
    if current in wrappers or not cli.exists():
        if not native.exists() or native.resolve() in wrappers:
            raise SystemExit('Default launcher has no official Claude binary; reinstall Claude Code first.')
        current = native.resolve(strict=True)
    if not (home / '.config/cliproxy-personal/client-key').is_file():
        raise SystemExit('Install the Personal gateway before making it the default.')
    contents = launcher.read_bytes()
    installed.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=installed.parent, delete=False) as temporary:
        temporary.write(contents)
        copied = Path(temporary.name)
        copied.chmod(0o755)
    copied.replace(installed)
    for path, target in ((native, current), (personal, installed), (cli, installed)):
        temporary = path.with_name(path.name + '.next')
        temporary.symlink_to(target)
        temporary.replace(path)
    print(f'{cli} defaults to Personal; official binary preserved at {native}.')


if __name__ == '__main__':
    install(Path.home(), Path(__file__).resolve().parent.parent)
