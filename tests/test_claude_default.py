import importlib.util
import os
from pathlib import Path
import runpy
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
launcher = runpy.run_path(str(ROOT / 'bin/claude-personal'))
spec = importlib.util.spec_from_file_location('install_claude_default', ROOT / 'bin/install-claude-default.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DefaultTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.tmp').mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.source = self.home / 'checkout'
        (self.source / 'bin').mkdir(parents=True)
        shutil.copyfile(ROOT / 'bin/claude-personal', self.source / 'bin/claude-personal')
        self.binary = self.home / 'official-claude'
        self.binary.write_text('official binary')
        (self.home / '.local/bin').mkdir(parents=True)
        (self.home / '.local/bin/claude').symlink_to(self.binary)
        key = self.home / '.config/cliproxy-personal/client-key'
        key.parent.mkdir(parents=True)
        key.write_text('personal-test-key\n')

    def invoke(self, command, env):
        installed = self.home / '.local/lib/claude-launcher'
        program = runpy.run_path(str(installed)) if installed.exists() else launcher
        with patch.dict(os.environ, env, clear=True), patch('pathlib.Path.home', return_value=self.home), \
                patch('sys.argv', [command, '--setting-sources', '', '--print', 'hello']), \
                patch('os.execve') as execute:
            program['main']()
        return execute.call_args.args

    def test_default_survives_disabled_settings_and_preserves_the_native_binary(self):
        installer.install(self.home, self.source)
        (self.home / '.local/bin/claude.next').symlink_to('stale-install')
        installer.install(self.home, self.source)
        installed = self.home / '.local/bin/claude'
        personal = self.home / '.local/bin/claude-personal'
        self.assertEqual(installed.resolve(), self.home / '.local/lib/claude-launcher')
        self.assertEqual(personal.resolve(), installed.resolve())
        shutil.rmtree(self.source)
        self.assertTrue(installed.is_file())
        self.assertTrue(os.access(installed, os.X_OK))
        cli, argv, env = self.invoke('claude', {})
        self.assertEqual(Path(cli).resolve(), self.binary)
        self.assertEqual(argv[1:], ['--setting-sources', '', '--print', 'hello'])
        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:8317')
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'personal-test-key')
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(self.home / '.claude-personal'))
        self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'], '')
        _, _, custom = self.invoke('claude', {'CLAUDE_CONFIG_DIR': '/custom-profile'})
        self.assertEqual(custom['CLAUDE_CONFIG_DIR'], '/custom-profile')
        self.assertEqual(custom['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:8317')

    def test_migrates_checkout_links_even_when_the_checkout_launcher_is_missing(self):
        cli = self.home / '.local/bin/claude'
        native = self.home / '.local/bin/claude-native'
        personal = self.home / '.local/bin/claude-personal'
        native.symlink_to(self.binary)
        cli.unlink()
        old = self.home / 'old-checkout/bin/claude-personal'
        old.parent.mkdir(parents=True)
        for exists, relinked in ((True, False), (False, False), (True, True)):
            with self.subTest(checkout_launcher_exists=exists, personal_relinked=relinked):
                old.write_text('old launcher')
                cli.unlink(missing_ok=True)
                personal.unlink(missing_ok=True)
                cli.symlink_to(old)
                personal.symlink_to(self.source / 'bin/claude-personal' if relinked else old)
                if not exists:
                    old.unlink()
                installer.install(self.home, self.source)
                self.assertEqual(native.resolve(), self.binary)
                self.assertEqual(cli.resolve().read_bytes(), (self.source / 'bin/claude-personal').read_bytes())
                self.assertEqual(personal.resolve(), cli.resolve())

    def test_explicit_api_and_cloud_providers_do_not_read_personal_credentials(self):
        installer.install(self.home, self.source)
        (self.home / '.config/cliproxy-personal/client-key').unlink()
        for env in ({'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8318', 'ANTHROPIC_AUTH_TOKEN': 'api-test-key',
                     'CLAUDE_CONFIG_DIR': '/api-profile'},
                    {'ANTHROPIC_API_KEY': 'direct-api-test-key'},
                    {'CLAUDE_CODE_USE_BEDROCK': '1'}):
            with self.subTest(env=env):
                for command in ('claude', str((self.home / '.local/bin/claude').resolve())):
                    with self.subTest(command=command):
                        _, _, actual = self.invoke(command, env)
                        self.assertEqual(actual, env)

    def test_personal_command_still_overrides_an_explicit_provider(self):
        _, _, env = self.invoke('claude-personal', {'ANTHROPIC_API_KEY': 'api-test-key',
                                                  'CLAUDE_CODE_USE_VERTEX': '1'})
        self.assertNotIn('CLAUDE_CODE_USE_VERTEX', env)
        self.assertEqual(env['ANTHROPIC_API_KEY'], '')
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'personal-test-key')

    def test_personal_uses_the_updated_official_binary_and_reports_a_missing_gateway_key(self):
        installer.install(self.home, self.source)
        updated = self.home / 'updated-claude'
        updated.write_text('updated official binary')
        cli = self.home / '.local/bin/claude'
        cli.unlink()
        cli.symlink_to(updated)
        executable, _, _ = self.invoke('claude-personal', {})
        self.assertEqual(Path(executable).resolve(), updated)
        (self.home / '.config/cliproxy-personal/client-key').unlink()
        with self.assertRaisesRegex(SystemExit, 'Personal gateway client key missing'):
            self.invoke('claude-personal', {})

    def test_missing_native_binary_refuses_instead_of_recursing(self):
        installer.install(self.home, self.source)
        self.binary.unlink()
        with self.assertRaisesRegex(SystemExit, 'Official Claude binary missing'):
            self.invoke('claude', {})


if __name__ == '__main__':
    unittest.main()
