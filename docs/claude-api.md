# Desktop Claude API-credit pool

Claude Personal and Claude API run as separate local services. Personal uses
port 8317; API uses port 8318 with no OAuth credentials, so heavy Personal
subagent work cannot spill into the API pool. Both require the desktop to stay
awake. The API pool retains its three keys, round-robin routing, session affinity,
and failover when a key returns the insufficient-credit error.

Run `claude-api-status.py` to see each key's successful and failed requests since
the gateway started. These counters are activity, not remaining tokens or money.
Use `--json` for a machine-readable report. The command makes only loopback reads
unless you explicitly pass `--refresh-billing`.

Exact remaining balances are in [Claude Console → Billing](https://platform.claude.com/settings/billing).
Select each linked Console organization and check Promotional credits for the
amount and expiry. Credits are denominated in dollars, not a fixed token count.
T3's subscription Limits view does not show this API-credit balance.

## Optional credit estimates

Anthropic's documented cost API reports organization-wide spending, not the
remaining credit balance. To estimate the remainder, create the private JSON file
`~/.config/cliproxy-api/billing.json` with one entry per Console organization:

```json
{
  "organizations": [
    {
      "organization_id": "YOUR_CONSOLE_ORGANIZATION_ID",
      "label": "Personal API credits",
      "credit_usd": "YOUR_FULL_MONTHLY_GRANT_IN_USD",
      "period_start": "YOUR_GRANT_TIMESTAMP_WITH_UTC_OFFSET",
      "period_end": "YOUR_EXPIRY_TIMESTAMP_WITH_UTC_OFFSET",
      "admin_key_file": "~/.config/cliproxy-api/billing-admin-key"
    }
  ]
}
```

Use the full grant before any period spending, not today's remaining balance.
Save the corresponding Admin API credential in the specified key file and set
its permissions to `600`. Never commit the JSON or keys. Multiple API keys in one
organization share one balance: do not create separate entries for them.

Run `claude-api-status.py --refresh-billing` to query only Anthropic's official
HTTPS cost endpoint with that credential. This does not generate inference.
The saved report contains no keys. Later `claude-api-status.py` invocations read
the cached estimate without contacting Anthropic. No refresh timer is installed.

The report subtracts the organization's reported spend from the configured grant,
shows the data-through timestamp and expiry, and hides a snapshot if the configured
period or grant changes or the period is inactive. Update the grant and dates on
each renewal; it never assumes an expired grant has replenished. Cost data usually
lags four hours and may lag 24 hours. Analytics rounds query boundaries to hours.
Purchased credits, mid-period grants, and spending not covered by the grant can
make this differ from the real promotional balance. Console remains authoritative.

Sources: [monthly API credits](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers)
and [Usage and Cost Analytics API](https://platform.claude.com/docs/en/manage-claude/usage-cost-analytics-api).

## Installation and recovery

The opt-in installer reuses the already installed, pinned CLIProxyAPI binary from
the Personal hub. It links to the resolved version, so a later Personal update
does not silently change the API service. Use `--binary /absolute/path` to select
a reviewed executable. Keep that executable available while this service uses it.

On first installation, pass a v8 JSON configuration containing `access.api-keys`
and `api-keys.claude` using `python3 bin/install-claude-api.py --import-config -`.
Stream it on stdin from the existing gateway; do not put secrets on the command
line or in the checkout. When the source uses YAML, parse it privately and serialize
to JSON before passing it to the installer. Only Claude API groups, access keys,
routing, and upstream settings are imported. Remote management settings, OAuth
credentials, other providers, and remote paths are not imported.

The new service binds only to `127.0.0.1:8318`, uses a new private management key,
and disables routine request logging. Upstream keeps its default ten error logs. Private files are under
`~/.config/cliproxy-api/` and `~/.local/share/cliproxy-api/`.

Rerun `python3 bin/install-claude-api.py` to refresh the unit and binary link while
preserving configured keys. It restarts only the API service; run it between
requests. Add `--configure-t3` to change the existing `claude_api_credits` provider's
base URL after the local gateway passes its authenticated model-list check. T3
watches its settings file, so it does not need a restart. This changes only the
endpoint; the provider ID, stored secret, profile, and conversation histories stay
intact. The prior settings are saved privately as
`~/.t3/userdata/settings.before-local-claude-api.json`. To roll back, change only
that provider's `ANTHROPIC_BASE_URL` to the old endpoint from the backup.

The NixOS service is retained for rollback and other clients. This installer never
disables it. Once all clients have moved, retire it through its NixOS configuration.

Check the local service with `systemctl --user status cliproxy-api.service`.
