import contextlib
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
import runpy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT/'bin/claude-proxy'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quota = load('quota', ROOT/'bin/claude-proxy-quota.py')
installer = load('installer', ROOT/'bin/install-claude-proxy.py')
NOW = datetime(2026, 10, 27, tzinfo=timezone.utc).timestamp()


def usage(weekly_reset='2026-10-30T20:00:00Z', session_used=5, weekly_used=50):
    return {'five_hour': {'utilization': session_used, 'resets_at': '2026-10-27T05:00:00Z'},
            'seven_day': {'utilization': weekly_used, 'resets_at': weekly_reset}}


class FakeAPI:
    def __init__(self, bodies):
        self.bodies = bodies
        self.patches = []
        self.calls = []

    def call(self, path, data=None, method=None):
        self.calls.append((path, data, method))
        if path == 'auth-files':
            return {'files': [
                {'name': key, 'auth_index': key, 'provider': 'claude', 'priority': 7}
                for key in self.bodies] + [
                    {'name': 'disabled', 'provider': 'claude', 'disabled': True},
                    {'name': 'codex', 'provider': 'codex'}]}
        if path == 'api-call':
            return {'status_code': 200, 'body': json.dumps(self.bodies[data['auth_index']])}
        if path == 'auth-files/fields':
            self.patches.append(data)
            return {'status': 'ok'}
        raise AssertionError(path)


class QuotaTest(unittest.TestCase):
    def test_soonest_weekly_reset_precedes_more_unused_quota(self):
        api = FakeAPI({'later': usage('2026-11-02T20:00:00Z', weekly_used=5), 'soon': usage(weekly_used=80)})
        result = quota.refresh(api, NOW)
        self.assertEqual([a['name'] for a in result['accounts']], ['soon', 'later'])
        self.assertEqual(api.patches, [{'name': 'soon', 'priority': 2}, {'name': 'later', 'priority': 1}])
        # Metadata-only patches cannot replace OAuth tokens or disable an account.
        self.assertTrue(all(set(p) == {'name', 'priority'} for p in api.patches))
        self.assertEqual(len([c for c in api.calls if c[0] == 'api-call']), 2)

    def test_exhausted_session_and_weekly_limits_deprioritized(self):
        api = FakeAPI({'session_full': usage(session_used=100), 'weekly_full': usage(weekly_used=100),
                       'available': usage('2026-11-02T00:00:00Z')})
        priorities = {a['name']: a['priority'] for a in quota.refresh(api, NOW)['accounts']}
        self.assertGreater(priorities['available'], 0)
        self.assertEqual(priorities['session_full'], -1)
        self.assertEqual(priorities['weekly_full'], -1)

    def test_malformed_usage_does_not_abort_other_accounts(self):
        for bad in (None, [], 3, 'no', {'five_hour': {'utilization': float('nan')}}):
            with self.subTest(bad=bad):
                api = FakeAPI({'bad': bad, 'good': usage()})
                accounts = quota.refresh(api, NOW)['accounts']
                self.assertEqual(accounts[0]['name'], 'good')
                self.assertEqual(accounts[1]['priority'], 0)

    def test_expired_window_is_unknown_not_replenished(self):
        body = usage('2026-10-26T00:00:00Z', weekly_used=99)
        self.assertIsNone(quota.summarize(body, NOW)['seven_day'])
        self.assertIsNone(quota.window({'utilization': 50, 'resets_at': None}, NOW))
        self.assertIsNone(quota.window({'utilization': True, 'resets_at': None}, NOW))
        self.assertIsNotNone(quota.window({'utilization': 0, 'resets_at': None}, NOW))

    def test_upstream_failure_becomes_unknown_without_response_leak(self):
        api = FakeAPI({'first': usage()})
        original = api.call
        def failing(path, data=None, method=None):
            if path == 'api-call':
                return {'status_code': 401, 'body': 'secret detail'}
            return original(path, data, method)
        api.call = failing
        result = quota.refresh(api, NOW)
        self.assertEqual(result['accounts'][0]['priority'], 0)
        self.assertNotIn('secret detail', json.dumps(result))

    def test_launcher_clears_other_provider_credentials_and_selectors(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/cliproxy-proxy'
            config.mkdir(parents=True)
            (config/'client-key').write_text('test-gateway-key')
            cli = home / '.local/bin/claude'
            cli.parent.mkdir(parents=True)
            cli.write_text('official binary')
            inherited = {'CLAUDE_CODE_USE_BEDROCK': '1', 'CLAUDE_CODE_USE_VERTEX': '1',
                         'CLAUDE_CODE_USE_FOUNDRY': '1', 'CLAUDE_CODE_USE_ANTHROPIC_AWS': '1',
                         'CLAUDE_CODE_OAUTH_TOKEN': 'other-oauth', 'ANTHROPIC_API_KEY': 'other-key'}
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, inherited), patch('os.execve') as execute:
                runpy.run_path(str(LAUNCHER), run_name='__main__')
            env = execute.call_args.args[2]
            self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'test-gateway-key')
            self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:8317')
            self.assertEqual(env['ANTHROPIC_API_KEY'], '')
            self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'], '')
            self.assertFalse(any(env.get(k) for k in inherited if k.startswith('CLAUDE_CODE_USE_')))

    def test_launcher_uses_its_own_profile_and_a_remote_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / '.config/cliproxy-proxy'
            config.mkdir(parents=True)
            (config/'client-key').write_text('key\n')
            (config/'base-url').write_text('http://desktop:8317\n')
            cli = home / '.local/bin/claude'
            cli.parent.mkdir(parents=True)
            cli.write_text('official binary')
            inherited = {'CLAUDE_CONFIG_DIR': str(home/'.claude'), 'ANTHROPIC_BASE_URL': 'http://other'}
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, inherited), patch('os.execve') as execute:
                runpy.run_path(str(LAUNCHER), run_name='__main__')
            path, argv, env = execute.call_args.args
            self.assertEqual(path, str(cli))
            self.assertEqual(env['CLAUDE_CONFIG_DIR'], str(home/'.claude-proxy'))
            self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://desktop:8317')

    def test_launcher_refuses_to_run_itself_as_claude(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home/'.config/cliproxy-proxy').mkdir(parents=True)
            (home/'.config/cliproxy-proxy/client-key').write_text('key')
            (home/'.local/bin').mkdir(parents=True)
            (home/'.local/bin/claude').symlink_to(LAUNCHER)
            with patch('pathlib.Path.home', return_value=home), patch('os.execve') as execute, \
                    self.assertRaises(SystemExit):
                runpy.run_path(str(LAUNCHER), run_name='__main__')
            execute.assert_not_called()

    def test_client_install_links_profile_and_stores_remote_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home/'.claude').mkdir()
            installer.install_client(home, ROOT)
            installer.use_gateway(home, 'desktop', lambda host: 'remote-key\n')
            self.assertEqual((home/'.local/bin/claude-proxy').resolve(), LAUNCHER)
            self.assertEqual((home/'.claude-proxy/CLAUDE.md').readlink(), home/'.claude/CLAUDE.md')
            self.assertEqual((home/'.claude-proxy').stat().st_mode & 0o777, 0o700)
            config = home/'.config/cliproxy-proxy'
            self.assertEqual((config/'client-key').read_text(), 'remote-key\n')
            self.assertEqual((config/'client-key').stat().st_mode & 0o777, 0o600)
            self.assertEqual((config/'base-url').read_text(), 'http://desktop:8317\n')
            # Reinstalling keeps working links instead of refusing them.
            installer.install_client(home, ROOT)

    def test_client_install_refuses_to_replace_a_regular_file(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home/'.local/bin').mkdir(parents=True)
            (home/'.local/bin/claude-proxy').write_text('someone else')
            with self.assertRaises(SystemExit):
                installer.install_client(home, ROOT)

    def test_t3_provider_needs_no_environment_and_keeps_other_settings(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home/'.t3/userdata/settings.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'theme': 'dark', 'providerInstances': {'claudeAgent': {'driver': 'claudeAgent'}}}))
            with contextlib.redirect_stdout(io.StringIO()):
                installer.configure_t3(home)
            settings = json.loads(path.read_text())
            self.assertEqual(settings['theme'], 'dark')
            self.assertIn('claudeAgent', settings['providerInstances'])
            instance = settings['providerInstances']['claude_proxy']
            self.assertNotIn('environment', instance)
            self.assertEqual(instance['config'], {'binaryPath': str(home/'.local/bin/claude-proxy'),
                                                  'homePath': str(home/'.claude-proxy')})

    def test_stale_cached_status_does_not_claim_remaining_quota(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(quota, 'STATE', Path(directory)):
            snapshot = quota.refresh(FakeAPI({'account': usage()}), NOW)
            snapshot['updated_at'] = '2020-01-01T00:00:00Z'
            quota.save(snapshot)
            self.assertEqual((Path(directory)/'quota.json').stat().st_mode & 0o777, 0o600)
            output = io.StringIO()
            with contextlib.redirect_stdout(output): quota.status()
            self.assertIn('[STALE]', output.getvalue())
            self.assertNotIn('% remaining', output.getvalue())


if __name__ == '__main__':
    unittest.main()
