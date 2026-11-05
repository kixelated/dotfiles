import importlib.util
import json
from pathlib import Path
import shutil
import stat
import tempfile
import tomllib
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    (ROOT / '.tmp').mkdir(exist_ok=True)


spec = importlib.util.spec_from_file_location('install_agent_defaults', ROOT / 'bin' / 'install-agent-defaults.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(dir=ROOT / '.tmp')
        self.addCleanup(directory.cleanup)
        self.home = Path(directory.name)

    def test_claude_merge_is_idempotent_and_preserves_settings(self):
        path = self.home / '.claude' / 'settings.json'
        path.parent.mkdir()
        hooks = {'SessionStart': [{'hooks': [{'type': 'command', 'command': 'notify'}]}]}
        path.write_text(json.dumps({'effortLevel': 'medium', 'promptCacheTtl': '1h', 'hooks': hooks}))
        path.chmod(0o640)
        self.assertTrue(installer.install_claude(path))
        installed = path.read_text()
        self.assertEqual(json.loads(installed), {**installer.CLAUDE, 'promptCacheTtl': '1h', 'hooks': hooks})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

        self.assertFalse(installer.install_claude(path))
        self.assertEqual(path.read_text(), installed)

    def test_claude_merge_keeps_other_env_and_models(self):
        path = self.home / '.claude' / 'settings.json'
        path.parent.mkdir()
        path.write_text(json.dumps({
            'env': {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8317', 'BASH_MAX_TIMEOUT_MS': '3600000'},
            'modelSettings': {'claude-opus-5-5': {'effortLevel': 'xhigh'}, 'claude-sonnet-5-5': {'autoCompactWindow': 'auto'}},
        }))
        self.assertTrue(installer.install_claude(path))
        settings = json.loads(path.read_text())
        self.assertEqual(settings['env'], {'ANTHROPIC_BASE_URL': 'http://127.0.0.1:8317', 'BASH_MAX_TIMEOUT_MS': '3300000'})
        self.assertEqual(settings['modelSettings'], {
            'claude-opus-5-5': {'effortLevel': 'xhigh', 'autoCompactWindow': 400000},
            'claude-sonnet-5-5': {'autoCompactWindow': 'auto'},
        })

    def test_new_claude_settings_file_is_private(self):
        path = self.home / '.claude-api-credits' / 'settings.json'
        self.assertTrue(installer.install_claude(path))
        self.assertEqual(json.loads(path.read_text()), installer.CLAUDE)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_codex_is_skipped_without_codex(self):
        codex_home = self.home / '.codex'
        with mock.patch.object(installer.shutil, 'which', return_value=None):
            self.assertFalse(installer.install_codex(codex_home))
        self.assertFalse(codex_home.exists())

    @unittest.skipUnless(shutil.which('codex'), 'codex is not installed')
    def test_codex_merge_is_idempotent_and_preserves_config(self):
        codex_home = self.home / '.codex'
        codex_home.mkdir()
        (codex_home / 'config.toml').write_text(
            'model = "gpt-6-sol"\nmodel_reasoning_effort = "high"\napproval_policy = "on-request"\n\n'
            '[hooks.state."/repo/.codex/hooks.json:session_start:0:0"]\ntrusted_hash = "sha256:other"\n')
        self.assertTrue(installer.install_codex(codex_home))
        configured = (codex_home / 'config.toml').read_text()
        config = tomllib.loads(configured)
        self.assertEqual(config['model'], 'gpt-6.1-sol')
        self.assertEqual(config['model_reasoning_effort'], 'xhigh')
        self.assertEqual(config['approval_policy'], 'on-request')
        self.assertEqual(config['hooks']['state']['/repo/.codex/hooks.json:session_start:0:0'],
                         {'trusted_hash': 'sha256:other'})

        self.assertFalse(installer.install_codex(codex_home))
        self.assertEqual((codex_home / 'config.toml').read_text(), configured)
