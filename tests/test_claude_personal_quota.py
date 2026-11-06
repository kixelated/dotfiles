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

spec = importlib.util.spec_from_file_location('quota', Path(__file__).resolve().parents[1]/'bin/claude-personal-quota.py')
quota = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quota)
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
            config = home / '.config/cliproxy-personal'
            config.mkdir(parents=True)
            (config/'client-key').write_text('test-gateway-key')
            inherited = {'CLAUDE_CODE_USE_BEDROCK': '1', 'CLAUDE_CODE_USE_VERTEX': '1',
                         'CLAUDE_CODE_USE_FOUNDRY': '1', 'CLAUDE_CODE_USE_ANTHROPIC_AWS': '1',
                         'CLAUDE_CODE_OAUTH_TOKEN': 'other-oauth', 'ANTHROPIC_API_KEY': 'other-key'}
            with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, inherited), patch('os.execve') as execute:
                runpy.run_path(str(Path(__file__).resolve().parents[1]/'bin/claude-personal'), run_name='__main__')
            env = execute.call_args.args[2]
            self.assertEqual(env['ANTHROPIC_AUTH_TOKEN'], 'test-gateway-key')
            self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:8317')
            self.assertEqual(env['ANTHROPIC_API_KEY'], '')
            self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'], '')
            self.assertFalse(any(env.get(k) for k in inherited if k.startswith('CLAUDE_CODE_USE_')))

    def test_stale_cached_status_does_not_claim_remaining_quota(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(quota, 'STATE', Path(directory)):
            snapshot = quota.refresh(FakeAPI({'personal': usage()}), NOW)
            snapshot['updated_at'] = '2020-01-01T00:00:00Z'
            quota.save(snapshot)
            self.assertEqual((Path(directory)/'quota.json').stat().st_mode & 0o777, 0o600)
            output = io.StringIO()
            with contextlib.redirect_stdout(output): quota.status()
            self.assertIn('[STALE]', output.getvalue())
            self.assertNotIn('% remaining', output.getvalue())


if __name__ == '__main__':
    unittest.main()
