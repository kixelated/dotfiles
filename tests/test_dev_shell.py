import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / 'bin' / 'dev-shell-hook'
DIRENV = shutil.which('direnv')


def setUpModule():
    (ROOT / '.tmp').mkdir(exist_ok=True)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'bin' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load('install_dev_shell', 'install-dev-shell.py')


def git(cwd, *args):
    subprocess.run(['git', *args], cwd=cwd, check=True, capture_output=True)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)

    def test_claude_merge_is_idempotent_and_preserves_settings(self):
        path = self.home / '.claude-personal' / 'settings.json'
        path.parent.mkdir()
        other = {'hooks': [{'type': 'command', 'command': 'notify'}]}
        path.write_text(json.dumps({'model': 'opus', 'promptCacheTtl': '1h',
                                    'hooks': {'SessionStart': [other], 'Stop': [other]}}))
        path.chmod(0o640)
        self.assertTrue(installer.update_json(path, 'claude'))
        installed = path.read_text()
        settings = json.loads(installed)
        self.assertEqual(settings['model'], 'opus')
        self.assertEqual(settings['promptCacheTtl'], '1h')
        self.assertEqual(settings['hooks']['Stop'], [other])
        self.assertEqual(settings['hooks']['SessionStart'], [other, installer.group('claude')])
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

        self.assertFalse(installer.update_json(path, 'claude'))
        self.assertEqual(path.read_text(), installed)

    def test_merge_replaces_an_older_hook_in_place(self):
        stale = {'hooks': [{'type': 'command', 'command': '/old/bin/dev-shell-hook claude'}]}
        other = {'hooks': [{'type': 'command', 'command': 'notify'}]}
        settings = {'hooks': {'SessionStart': [stale, other, stale]}}
        self.assertTrue(installer.merge(settings, 'claude'))
        self.assertEqual(settings['hooks']['SessionStart'], [installer.group('claude'), other])

    def test_new_settings_file_is_private(self):
        path = self.home / '.claude' / 'settings.json'
        installer.update_json(path, 'claude')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text()), {'hooks': {'SessionStart': [installer.group('claude')]}})

    def test_codex_without_codex_installs_hook_and_loader_only(self):
        codex_home = self.home / '.codex'
        with mock.patch.object(installer.shutil, 'which', return_value=None):
            installer.install_codex(codex_home)
            installer.install_codex(codex_home)
        hooks = json.loads((codex_home / 'hooks.json').read_text())
        self.assertEqual(hooks, {'hooks': {'SessionStart': [installer.group('codex')]}})
        self.assertEqual((codex_home / 'bash-env.sh').resolve(), ROOT / 'codex' / 'bash-env.sh')
        self.assertFalse((codex_home / 'config.toml').exists())

    @unittest.skipUnless(shutil.which('codex'), 'codex is not installed')
    def test_codex_trusts_the_hook_and_sets_bash_env(self):
        codex_home = self.home / '.codex'
        codex_home.mkdir()
        other = '[hooks.state."/repo/.codex/hooks.json:session_start:0:0"]\ntrusted_hash = "sha256:other"\n'
        (codex_home / 'config.toml').write_text(other)
        installer.install_codex(codex_home)
        configured = (codex_home / 'config.toml').read_text()
        self.assertIn('trusted_hash = "sha256:other"', configured)
        self.assertIn(f'BASH_ENV = "{codex_home / "bash-env.sh"}"', configured)

        installer.install_codex(codex_home)
        self.assertEqual((codex_home / 'config.toml').read_text(), configured)
        server = installer.AppServer(codex_home)
        try:
            listed = server.request('hooks/list', {'cwds': [str(self.home)]})
        finally:
            server.close()
        hooks = [hook for entry in listed['data'] for hook in entry['hooks'] if hook['source'] == 'user']
        self.assertEqual([(hook['command'], hook['trustStatus']) for hook in hooks],
                         [(installer.command('codex'), 'trusted')])


class HookTests(unittest.TestCase):
    """Run the hook against disposable checkouts and an isolated direnv state."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        self.env = {
            'HOME': str(self.home),
            'XDG_CONFIG_HOME': str(self.home / '.config'),
            'XDG_DATA_HOME': str(self.home / '.local/share'),
            'XDG_CACHE_HOME': str(self.home / '.cache'),
            'PATH': os.environ['PATH'],
            'LANG': 'C.UTF-8',
            'GIT_CONFIG_GLOBAL': '/dev/null',
            'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.com',
            'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.com',
            'INHERITED': 'kept',
            'REMOVED': 'by-envrc',
        }
        self.env_file = self.root / 'session-env.sh'
        self.env_file.touch()

        upstream = self.root / 'upstream'
        upstream.mkdir()
        git(upstream, 'init', '-q', '-b', 'main')
        (upstream / '.envrc').write_text('export DEV_SHELL_TEST="loaded value\'s"\nunset REMOVED\n')
        (upstream / 'flake.nix').write_text('{ }\n')
        (upstream / 'flake.lock').write_text('{"version": 7}\n')
        git(upstream, 'add', '.')
        git(upstream, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', 'init')
        self.checkout = self.root / 'checkout'
        git(self.root, 'clone', '-q', str(upstream), str(self.checkout))

    def run_hook(self, mode='claude', **overrides):
        env = {**self.env, 'CLAUDE_ENV_FILE': str(self.env_file), 'CLAUDE_PROJECT_DIR': str(self.checkout)}
        env.update(overrides)
        env = {key: value for key, value in env.items() if value is not None}
        return subprocess.run([str(HOOK), mode], cwd=self.checkout, env=env, capture_output=True, text=True)

    def allowed(self):
        result = subprocess.run(['direnv', 'status', '--json'], cwd=self.checkout, env=self.env,
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)['state']['foundRC']['allowed'] == 0

    def source(self, script):
        """Variables a fresh bash sees after running `script`."""
        result = subprocess.run(['bash', '-c', script + '\nprintf "%s|%s|%s" "$DEV_SHELL_TEST" "$INHERITED" "${REMOVED-unset}"'],
                                cwd=self.checkout, env=self.env, capture_output=True, text=True, check=True)
        return result.stdout

    def test_noop_without_direnv(self):
        bare = self.root / 'bare-bin'
        bare.mkdir()
        for tool in ('git', 'python3'):
            (bare / tool).symlink_to(shutil.which(tool))
        result = self.run_hook(PATH=str(bare))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))
        self.assertEqual(self.env_file.read_text(), '')

    def test_noop_without_envrc_or_session(self):
        (self.checkout / '.envrc').unlink()
        self.assertEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.run_hook('codex').returncode, 0)
        self.assertEqual(self.env_file.read_text(), '')
        self.assertFalse((self.checkout / '.direnv').exists())
        (self.checkout / '.envrc').write_text('export DEV_SHELL_TEST=1\n')
        for missing in ('CLAUDE_ENV_FILE', 'CLAUDE_PROJECT_DIR'):
            self.assertEqual(self.run_hook(**{missing: None}).returncode, 0)
        self.assertEqual(self.env_file.read_text(), '')

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_matching_checkout_is_allowed_and_loaded_for_claude(self):
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.allowed())
        sidecar = Path(str(self.env_file) + '.dev-shell')
        self.assertEqual(stat.S_IMODE(sidecar.stat().st_mode), 0o600)
        # Only the diff is captured, so untouched variables are not re-exported.
        self.assertNotIn('INHERITED', sidecar.read_text())
        self.assertEqual(self.source(f'. {self.env_file}'), "loaded value's|kept|unset")

        # A second SessionStart refreshes the sidecar without another sourcing line.
        self.assertEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.env_file.read_text().count('.dev-shell'), 1)

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_matching_checkout_is_loaded_for_codex(self):
        result = self.run_hook('codex', CLAUDE_ENV_FILE=None, CLAUDE_PROJECT_DIR=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.allowed())
        loader = ROOT / 'codex' / 'bash-env.sh'
        self.assertEqual(self.source(f'. {loader}'), "loaded value's|kept|unset")
        # Codex's shell snapshot restores its own environment after BASH_ENV
        # runs, then execs the command in an inner bash, which must reload it.
        wrapped = subprocess.run(
            ['bash', '-c', 'export DEV_SHELL_TEST=from-codex-snapshot REMOVED=by-envrc\n'
                           'exec bash -c \'printf "%s|%s|%s" "$DEV_SHELL_TEST" "$INHERITED" "${REMOVED-unset}"\''],
            cwd=self.checkout, env={**self.env, 'BASH_ENV': str(loader)}, capture_output=True, text=True, check=True)
        self.assertEqual(wrapped.stdout, "loaded value's|kept|unset")

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_changed_reviewed_files_need_a_manual_allow(self):
        for name, contents in (('.envrc', 'export DEV_SHELL_TEST=edited\n'), ('flake.lock', '{"version": 8}\n')):
            with self.subTest(name=name):
                original = (self.checkout / name).read_text()
                (self.checkout / name).write_text(contents)
                result = self.run_hook()
                self.assertEqual(result.returncode, 1)
                self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
                self.assertIn(f'{name} changed from origin/main', result.stderr)
                self.assertIn('direnv allow', result.stderr)
                self.assertFalse(self.allowed())
                self.assertEqual(self.env_file.read_text(), '')
                (self.checkout / name).write_text(original)

    def commit(self, repo, name='README', message='change'):
        (repo / name).write_text(message + '\n')
        git(repo, 'add', name)
        git(repo, '-c', 'commit.gpgsign=false', 'commit', '-q', '-m', message)

    def assert_off_origin(self, result):
        self.assertEqual(result.returncode, 1)
        self.assertEqual(len(result.stderr.splitlines()), 1, result.stderr)
        self.assertIn("HEAD isn't on any origin branch", result.stderr)
        self.assertIn('direnv allow', result.stderr)
        self.assertFalse(self.allowed())
        self.assertEqual(self.env_file.read_text(), '')

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_head_on_another_origin_branch_is_allowed(self):
        upstream = self.root / 'upstream'
        git(upstream, 'checkout', '-q', '-b', 'feature')
        self.commit(upstream)
        git(upstream, 'checkout', '-q', 'main')
        git(self.checkout, 'fetch', '-q', 'origin')
        git(self.checkout, 'checkout', '-q', '--detach', 'origin/feature')
        result = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.allowed())

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_unpushed_commit_needs_a_manual_allow(self):
        self.commit(self.checkout)
        self.assert_off_origin(self.run_hook())

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_fork_head_needs_a_manual_allow(self):
        fork = self.root / 'fork'
        git(self.root, 'clone', '-q', str(self.root / 'upstream'), str(fork))
        self.commit(fork, message='contribution')
        git(self.checkout, 'remote', 'add', 'contributor', str(fork))
        git(self.checkout, 'fetch', '-q', 'contributor')
        git(self.checkout, 'checkout', '-q', '-b', 'pr', 'contributor/main')
        # The reviewed files still match origin/main; only HEAD's origin differs.
        self.assert_off_origin(self.run_hook())

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_untracked_envrc_is_not_allowed(self):
        sub = self.checkout / 'tool'
        sub.mkdir()
        (sub / '.envrc').write_text('export DEV_SHELL_TEST=1\n')
        result = self.run_hook(CLAUDE_PROJECT_DIR=str(sub))
        self.assertEqual(result.returncode, 1)
        self.assertIn('.envrc changed from origin/main', result.stderr)

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_missing_default_ref_needs_a_manual_allow(self):
        git(self.checkout, 'remote', 'set-head', 'origin', '-d')
        result = self.run_hook()
        self.assertEqual(result.returncode, 1)
        self.assertIn('default branch is unknown', result.stderr)
        self.assertFalse(self.allowed())

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_denied_envrc_stays_denied(self):
        subprocess.run(['direnv', 'deny', str(self.checkout)], env=self.env, check=True, capture_output=True)
        result = self.run_hook()
        self.assertEqual(result.returncode, 1)
        self.assertIn('denied', result.stderr)
        self.assertFalse(self.allowed())

    @unittest.skipUnless(DIRENV, 'direnv is not installed')
    def test_manually_allowed_changes_load(self):
        (self.checkout / '.envrc').write_text('export DEV_SHELL_TEST=edited\n')
        subprocess.run(['direnv', 'allow', str(self.checkout)], env=self.env, check=True, capture_output=True)
        self.assertEqual(self.run_hook().returncode, 0)
        self.assertEqual(self.source(f'. {self.env_file}'), 'edited|kept|by-envrc')


if __name__ == '__main__':
    unittest.main()
