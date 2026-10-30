import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    (ROOT / '.tmp').mkdir(exist_ok=True)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'bin' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load('install_claude_api', 'install-claude-api.py')
status = load('claude_api_status', 'claude-api-status.py')


class GatewayTests(unittest.TestCase):
    def test_migration_retains_api_failover_but_excludes_subscription_credentials(self):
        imported = {
            'access': {'api-keys': ['gateway-test-key']},
            'api-keys': {'claude': [{'name': 'credits', 'keys': [{'api-key': 'test-api'}],
                                    'request-scoped-errors': [{'status': 400, 'match': ['credit balance is too low'],
                                                               'action': 'continue-and-cooldown'}]}],
                         'codex': [{'keys': [{'api-key': 'unrelated'}]}]},
            'routing': {'session-affinity': True, 'strategy': 'round-robin'},
            'oauth': {'auth-dir': '/remote/subscriptions'},
            'management': {'allow-remote': True, 'secret-key': 'remote-management-key'},
        }
        new = installer.gateway_config(imported, Path('/private/state'), 'new-management-key')
        self.assertEqual(new['api-keys'], {'claude': imported['api-keys']['claude']})
        self.assertEqual(new['routing'], imported['routing'])
        self.assertEqual(new['server']['host'], '127.0.0.1')
        self.assertEqual(new['server']['port'], 8318)
        self.assertFalse(new['management']['allow-remote'])
        self.assertEqual(new['management']['secret-key'], 'new-management-key')
        self.assertEqual(new['oauth'], {'auth-dir': '/private/state/auth'})
        self.assertFalse(new['observability']['logs']['request-log'])

    def test_t3_switch_preserves_profiles_and_redacted_secrets(self):
        original = {'providerInstances': {
            'claude_personal': {'config': {'homePath': '/personal'}},
            'claude_api_credits': {'config': {'homePath': '/api'}, 'environment': [
                {'name': 'ANTHROPIC_BASE_URL', 'value': 'https://old-gateway'},
                {'name': 'ANTHROPIC_AUTH_TOKEN', 'value': '', 'sensitive': True, 'valueRedacted': True}]}}}
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            path = Path(directory) / 'settings.json'
            path.write_text(json.dumps(original))
            installer.update_t3(path)
            updated = json.loads(path.read_text())
            original['providerInstances']['claude_api_credits']['environment'][0]['value'] = 'http://127.0.0.1:8318'
            self.assertEqual(updated, original)
            self.assertEqual(json.loads((Path(directory) / 'settings.before-local-claude-api.json').read_text())
                             ['providerInstances']['claude_api_credits']['environment'][0]['value'], 'https://old-gateway')
            installer.update_t3(path)
            self.assertEqual(json.loads(path.read_text()), updated)


class BillingTests(unittest.TestCase):
    def test_organization_spend_pagination_cents_and_expiry(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            key = Path(directory) / 'key'
            key.write_text('fake-admin-key')
            key.chmod(0o600)
            account = {'organization_id': 'org-test', 'label': 'Test', 'credit_usd': '200',
                       'period_start': '2026-10-15T00:00:00Z', 'period_end': '2026-11-15T00:00:00Z',
                       'admin_key_file': str(key)}
            calls = []
            def get(url, headers):
                calls.append(url)
                self.assertTrue(url.startswith(status.COST_API + '?'))
                self.assertEqual(headers['x-api-key'], 'fake-admin-key')
                return {'data_refreshed_at': '2026-10-29T12:00:00Z',
                        'data': [{'cost': {'amount': '1250.000000', 'currency': 'USD'}}],
                        'has_more': len(calls) == 1, 'next_page': 'page-two'}
            now = datetime(2026, 10, 29, 15, tzinfo=timezone.utc)
            result = status.fetch_billing(account, now, get)
            self.assertEqual(len(calls), 2)
            self.assertIn('page=page-two', calls[1])
            self.assertEqual(status.amount(result['reported_spend_usd']), 25)
            self.assertEqual(status.amount(result['remaining_estimate_usd']), 175)
            self.assertEqual(result['data_through'], '2026-10-29T12:00:00+00:00')
            self.assertNotIn('fake-admin-key', json.dumps(result))
            with self.assertRaises(ValueError):
                status.fetch_billing(account, datetime(2026, 11, 15, tzinfo=timezone.utc), get)
            self.assertEqual(len(calls), 2)
            account['credit_usd'] = '100'
            self.assertNotEqual(result['period_id'], status.period_id(account))

    def test_missing_billing_snapshot_is_unknown_not_zero_spend(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.tmp') as directory:
            key = Path(directory) / 'key'
            key.write_text('fake')
            key.chmod(0o600)
            account = {'organization_id': 'org', 'label': 'Test', 'credit_usd': '200',
                       'period_start': '2026-10-01T00:00:00Z', 'period_end': '2026-11-01T00:00:00Z',
                       'admin_key_file': str(key)}
            with self.assertRaises(ValueError):
                status.fetch_billing(account, datetime(2026, 10, 29, tzinfo=timezone.utc),
                                     lambda *_: {'data': [], 'data_refreshed_at': None})

    def test_do_not_double_count_one_organization_or_accept_invalid_amounts(self):
        account = {'organization_id': 'org', 'label': 'Test', 'credit_usd': '200',
                   'period_start': '2026-10-01T00:00:00Z', 'period_end': '2026-11-01T00:00:00Z',
                   'admin_key_file': '/private/key'}
        with self.assertRaises(ValueError):
            status.validate_accounts([account, account])
        for value in ('NaN', 'Infinity', '-1'):
            with self.assertRaises(ValueError):
                status.amount(value)


if __name__ == '__main__':
    unittest.main()
