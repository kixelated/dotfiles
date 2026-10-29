#!/usr/bin/env python3
"""Prefer personal Claude subscriptions whose weekly allowance resets soonest.

OAuth tokens stay in CLIProxyAPI. Only its loopback management API handles them.
Existing session affinity and upstream cooldowns remain owned by CLIProxyAPI.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import urllib.request

CONFIG = Path.home() / '.config/cliproxy-personal'
STATE = Path.home() / '.local/share/cliproxy-personal'
BASE = 'http://127.0.0.1:8317/v0/management/'


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def window(value, now):
    if not isinstance(value, dict):
        return None
    used = value.get('utilization')
    if isinstance(used, bool) or not isinstance(used, (float, int)) or not math.isfinite(used) or used < 0:
        return None
    reset = timestamp(value.get('resets_at'))
    # Never extrapolate a fresh allowance from an expired or malformed window.
    if (reset is not None and reset <= now) or (used > 0 and reset is None):
        return None
    return {'used_percent': used, 'resets_at': value.get('resets_at')}


def summarize(body, now):
    if not isinstance(body, dict):
        raise ValueError('Usage response is not an object')
    return {name: window(body.get(name), now) for name in ('five_hour', 'seven_day')}


def ranking(usage):
    """Available accounts first; unknown next; exhausted last. Weekly reset wins."""
    windows = [usage.get(k) for k in ('five_hour', 'seven_day')]
    if any(w and w['used_percent'] >= 100 for w in windows):
        return (2, math.inf, math.inf)
    if any(w is None for w in windows):
        return (1, math.inf, math.inf)
    return (0, timestamp(windows[1]['resets_at']) or math.inf,
            timestamp(windows[0]['resets_at']) or math.inf)


class API:
    def __init__(self):
        self.key = (CONFIG / 'management-key').read_text().strip()
        # Local management traffic must not inherit a shell's HTTP proxy.
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, path, data=None, method=None):
        body = None if data is None else json.dumps(data).encode()
        req = urllib.request.Request(BASE + path, data=body, method=method,
                                     headers={'Authorization': 'Bearer ' + self.key,
                                              'Content-Type': 'application/json'})
        with self.http.open(req, timeout=75) as response:
            return json.load(response)


def refresh(api, now):
    accounts = []
    for auth in api.call('auth-files')['files']:
        if auth.get('provider') != 'claude' or auth.get('disabled'):
            continue
        usage = {'five_hour': None, 'seven_day': None}
        error = None
        try:
            response = api.call('api-call', {
                'auth_index': auth['auth_index'], 'method': 'GET',
                'url': 'https://api.anthropic.com/api/oauth/usage',
                'header': {'Authorization': 'Bearer $TOKEN$',
                           'anthropic-beta': 'oauth-2025-04-20',
                           'User-Agent': 'personal-claude-router/1.0'}})
            if response['status_code'] == 200:
                usage = summarize(json.loads(response['body']), now)
            else:
                error = 'Usage HTTP ' + str(response['status_code'])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Responses/errors may contain secrets: retain only the error class.
            error = type(exc).__name__
        accounts.append({'name': auth['name'], 'label': auth.get('email') or auth.get('label') or auth['name'],
                         'usage': usage, 'error': error,
                         'previous_priority': auth.get('priority', 0)})
    accounts.sort(key=lambda a: (*ranking(a['usage']), a['name']))
    for position, account in enumerate(accounts):
        group = ranking(account['usage'])[0]
        priority = len(accounts) - position if group == 0 else (0 if group == 1 else -1)
        if account.pop('previous_priority') != priority:
            api.call('auth-files/fields', {'name': account['name'], 'priority': priority}, 'PATCH')
        account['priority'] = priority
    return {'updated_at': datetime.fromtimestamp(now, timezone.utc).isoformat(), 'accounts': accounts}


def save(snapshot):
    target = STATE / 'quota.json'
    temporary = STATE / 'quota.json.new'
    with temporary.open('w') as output:
        json.dump(snapshot, output, indent=2)
        output.write('\n')
    temporary.chmod(0o600)
    temporary.replace(target)


def status():
    if not (STATE / 'quota.json').exists():
        raise SystemExit('No usage snapshot yet. Run: systemctl --user start claude-personal-quota.service')
    snapshot = json.loads((STATE / 'quota.json').read_text())
    now = datetime.now(timezone.utc).timestamp()
    checked = timestamp(snapshot.get('updated_at'))
    stale = checked is None or now - checked > 2 * 5 * 60 or checked > now
    print('Usage checked:', snapshot['updated_at'], '(UTC)', '[STALE]' if stale else '')
    for account in snapshot['accounts']:
        print(account['label'] + ' — priority ' + str(account['priority']))
        for key, label in [('five_hour', 'Session'), ('seven_day', 'Weekly')]:
            w = account['usage'][key]
            if stale or w is None or (timestamp(w['resets_at']) is not None and timestamp(w['resets_at']) <= now):
                print('  ' + label + ': unknown')
                continue
            when = timestamp(w['resets_at'])
            reset = datetime.fromtimestamp(when).astimezone().strftime('%a %b %d %I:%M %p %Z') if when else 'not started'
            print(f"  {label}: {max(0, 100 - w['used_percent']):g}% remaining; reset {reset}")
        if account['error']:
            print('  ' + account['error'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--status', action='store_true', help='Show the cached quota snapshot without making requests')
    args = parser.parse_args()
    os.umask(0o077)
    if args.status:
        status()
        return
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (STATE / 'quota.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        snapshot = refresh(API(), datetime.now(timezone.utc).timestamp())
        save(snapshot)
        print('Updated reset-aware priorities for', len(snapshot['accounts']), 'personal Claude accounts.')


if __name__ == '__main__':
    main()
