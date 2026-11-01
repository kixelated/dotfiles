import importlib.util
import os
from pathlib import Path
import runpy
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
        self.binary = self.home / 'official-claude'
        self.binary.write_text('official binary')
        (self.home / '.local/bin').mkdir(parents=True)
        (self.home / '.local/bin/claude').symlink_to(self.binary)
        key = self.home / '.config/cliproxy-personal/client-key'
        key.parent.mkdir(parents=True)
        key.write_text('personal-test-key\n')

    def invoke(self, command, env):
        with patch.dict(os.environ, env, clear=True), patch('pathlib.Path.home', return_value=self.home), \
                patch('sys.argv', [command, '--setting-sources', '', '--print', 'hello']), \
                patch('os.execve') as execute:
            launcher['main']()
        return execute.call_args.args

    def test_default_survives_disabled_settings_and_preserves_the_native_binary(self):
        installer.install(self.home, ROOT)
        installer.install(self.home, ROOT)
        cli, argv, env = self.invoke('claude', {})
        self.assertEqual(Path(cli).resolve(), self.binary)
        self.assertEqual(argv[1:], ['--setting-sources', '', '--print', 'hello'])
        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:8317')
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'personal-test-key')
        self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(self.home / '.claude-personal'))
        self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'], '')

    def test_explicit_api_and_cloud_providers_do_not_read_personal_credentials(self):
        installer.install(self.home, ROOT)
        (self.home / '.config/cliproxy-personal/client-key').unlink()
        for env in ({'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8318', 'ANTHROPIC_AUTH_TOKEN': 'api-test-key',
                     'CLAUDE_CONFIG_DIR': '/api-profile'},
                    {'ANTHROPIC_API_KEY': 'direct-api-test-key'},
                    {'CLAUDE_CODE_USE_BEDROCK': '1'}):
            with self.subTest(env=env):
                _, _, actual = self.invoke('claude', env)
                self.assertEqual(actual, env)

    def test_personal_command_still_overrides_an_explicit_provider(self):
        _, _, env = self.invoke('claude-personal', {'ANTHROPIC_API_KEY': 'api-test-key',
                                                  'CLAUDE_CODE_USE_VERTEX': '1'})
        self.assertNotIn('CLAUDE_CODE_USE_VERTEX', env)
        self.assertEqual(env['ANTHROPIC_API_KEY'], '')
        self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'personal-test-key')

    def test_missing_native_binary_refuses_instead_of_recursing(self):
        installer.install(self.home, ROOT)
        self.binary.unlink()
        with self.assertRaisesRegex(SystemExit, 'Official Claude binary missing'):
            self.invoke('claude', {})


if __name__ == '__main__':
    unittest.main()
