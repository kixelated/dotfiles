#!/usr/bin/env python3
"""Show local API-key activity and optional billing-period credit estimates."""
import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

CONFIG = Path.home() / '.config/cliproxy-api'
STATE = Path.home() / '.local/share/cliproxy-api'
CONSOLE = 'https://platform.claude.com/settings/billing'
COST_API = 'https://api.anthropic.com/v1/organizations/analytics/cost'


def timestamp(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Billing timestamps require a UTC offset')
    return result.astimezone(timezone.utc)


def amount(value):
    result = Decimal(str(value))
    if not result.is_finite() or result < 0:
        raise ValueError('Amounts must be finite and nonnegative')
    return result


def period_id(account):
    value = {key: account[key] for key in ('organization_id', 'credit_usd', 'period_start', 'period_end')}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def validate_accounts(accounts):
    seen = set()
    for account in accounts:
        org = account['organization_id']
        if not org or org in seen:
            raise ValueError('Configure each Console organization once, regardless of API-key count')
        seen.add(org)
        amount(account['credit_usd'])
        if timestamp(account['period_start']) >= timestamp(account['period_end']):
            raise ValueError('Invalid billing period')
        if not account.get('label') or not account.get('admin_key_file'):
            raise ValueError('Each organization needs a label and admin_key_file')
    return accounts


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(url, headers):
    http = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    request = urllib.request.Request(url, headers=headers)
    with http.open(request, timeout=20) as response:
        return json.load(response)


def local_activity():
    key = (CONFIG / 'management-key').read_text().strip()
    headers = {'Authorization': 'Bearer ' + key}
    base = 'http://127.0.0.1:8318/v8/management/'
    groups = get_json(base + 'config/api-keys/claude', headers)
    usage = get_json(base + 'observability/usage/api-keys', headers).get('claude', {})
    output = []
    for group in groups:
        for credential in group.get('keys', []):
            base_url = credential.get('base-url', group.get('base-url', ''))
            record = usage.get(base_url + '|' + credential['api-key'], {})
            output.append({'label': f'API key {len(output) + 1}',
                           'success': record.get('success', 0), 'failed': record.get('failed', 0)})
    return output


def fetch_billing(account, now, get=get_json):
    start, end = timestamp(account['period_start']), timestamp(account['period_end'])
    if not start <= now < end:
        raise ValueError('Billing period is inactive; update its grant and expiry before refreshing')
    key_file = Path(account['admin_key_file']).expanduser()
    if key_file.stat().st_mode & 0o077:
        raise ValueError('Billing key file must be private (chmod 600)')
    headers = {'x-api-key': key_file.read_text().strip(), 'anthropic-version': '2023-06-01',
               'anthropic-beta': 'analytics-usage-cost-2026-08-24'}
    total = Decimal('0')
    refreshed = None
    # Analytics queries span at most 31 days, even when billing cycles are longer.
    cursor = start
    while cursor < now:
        until = min(cursor + timedelta(days=31), now)
        page = None
        seen = set()
        while True:
            query = {'starting_at': cursor.isoformat(), 'ending_at': until.isoformat(), 'limit': 1000}
            if page:
                query['page'] = page
            response = get(COST_API + '?' + urllib.parse.urlencode(query), headers)
            if not response.get('data_refreshed_at'):
                raise ValueError('No billing snapshot available yet')
            data_time = timestamp(response['data_refreshed_at'])
            if data_time > now:
                raise ValueError('Billing snapshot timestamp is in the future')
            refreshed = data_time if refreshed is None else min(refreshed, data_time)
            for row in response['data']:
                if row['cost']['currency'] != 'USD':
                    raise ValueError('Expected USD billing data')
                # Anthropic returns decimal strings in cents, before credits.
                total += amount(row['cost']['amount']) / 100
            if not response.get('has_more'):
                break
            page = response.get('next_page')
            if not page or page in seen:
                raise ValueError('Invalid billing pagination')
            seen.add(page)
        cursor = until
    refreshed = min(refreshed, now.replace(minute=0, second=0, microsecond=0))
    if refreshed < start:
        raise ValueError('Billing data does not cover this credit period yet')
    grant = amount(account['credit_usd'])
    return {'period_id': period_id(account), 'label': account['label'],
            'reported_spend_usd': str(total), 'remaining_estimate_usd': str(max(Decimal('0'), grant - total)),
            'data_through': refreshed.isoformat(), 'checked_at': now.isoformat(), 'expires_at': end.isoformat()}


def save(snapshot):
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = STATE / 'billing.json'
    temporary = STATE / 'billing.json.new'
    temporary.write_text(json.dumps(snapshot, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-billing', action='store_true', help='Send configured admin credentials to Anthropic’s cost-report endpoint')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    now = datetime.now(timezone.utc)
    report = {'gateway': 'http://127.0.0.1:8318', 'console': CONSOLE, 'accounts': [], 'billing': [], 'errors': []}
    try:
        report['accounts'] = local_activity()
    except (OSError, ValueError, KeyError, TypeError) as error:
        report['errors'].append('Local gateway unavailable: ' + type(error).__name__)
    config_file = CONFIG / 'billing.json'
    accounts = validate_accounts(json.loads(config_file.read_text())['organizations']) if config_file.exists() else []
    cache_file = STATE / 'billing.json'
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    if args.refresh_billing:
        if not accounts:
            report['errors'].append('Billing access is not configured. See docs/claude-api.md.')
        for account in accounts:
            try:
                cache[account['organization_id']] = fetch_billing(account, now)
            except (OSError, ValueError, KeyError, TypeError, ArithmeticError) as error:
                # Upstream bodies and headers can contain credentials; never print them.
                detail = f'HTTP {error.code}' if isinstance(error, urllib.error.HTTPError) else type(error).__name__
                report['errors'].append(account['label'] + ': billing refresh failed (' + detail + ')')
        save(cache)
    for account in accounts:
        snapshot = cache.get(account['organization_id'])
        valid = (snapshot and snapshot.get('period_id') == period_id(account)
                 and timestamp(account['period_start']) <= now < timestamp(account['period_end']))
        report['billing'].append(snapshot if valid else {'label': account['label'], 'remaining_estimate_usd': None})
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print('Claude API — local desktop, port 8318')
        for account in report['accounts']:
            print(f"  {account['label']}: {account['success']} successful / {account['failed']} failed requests since gateway start")
        if not report['billing']:
            print('Remaining API credits: unknown — billing access is not configured.')
        for entry in report['billing']:
            balance = entry['remaining_estimate_usd']
            if balance is None:
                print(entry['label'] + ': remaining API credits unknown — no current-period snapshot')
            else:
                print(f"{entry['label']}: ~${Decimal(balance):.2f} remaining; reported spend ${Decimal(entry['reported_spend_usd']):.2f}")
                print('  Data through ' + entry['data_through'] + '; credits expire ' + entry['expires_at'])
        print('Exact balances and expiry: ' + CONSOLE)
        print('Billing estimates can lag 4–24 hours and exclude usage after the data-through time.')
        for error in report['errors']:
            print(error)
    if report['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
