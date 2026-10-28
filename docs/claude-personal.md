# Personal Claude hub on Ubuntu

This is an opt-in hub for personal Max subscriptions. Work Claude logins on the
NixOS hosts remain separate. Subscription proxying carries provider-policy risk;
this setup was requested with that risk accepted. The official Claude Code binary
runs the agent; CLIProxyAPI forwards its model requests.

## Use

- In Ubuntu's T3 environment, choose **Claude Personal**. It uses a separate
  `~/.claude-personal` profile and the localhost gateway. The **Claude API** provider
  remains the separate three-key API-credit pool on the NixOS gateway.
- In T3’s **Usage → Limits**, the **Claude Personal** hub shows all three accounts.
- In a terminal, run `claude-personal` with the usual Claude Code arguments.
- Show account usage: `claude-personal-quota.py --status`.
- Refresh now: `systemctl --user start claude-personal-quota.service`.
- Check services: `systemctl --user status cliproxy-personal.service claude-personal-quota.timer`.

The hub listens only on `127.0.0.1:8317`. This desktop's T3 provider can use it
without Tailscale or a running NixOS host. A remote T3 client uses the provider on
Ubuntu; it does not need direct access to the proxy. No remote proxy endpoint is
published by this installer. The desktop must be awake for its agents to run.

## Install and update

Run `python3 bin/install-claude-personal.py` from this dotfiles checkout. This
installer is intentionally separate from the general dotfiles installer and
refuses NixOS hosts. It installs a pinned official Linux x86_64 binary, verifies
the release archive's SHA-256 when downloading, creates private credentials if
missing, and enables the user service and quota timer. Re-running preserves the
configuration, gateway keys and saved logins. Updates require reviewing/changing
`VERSION` and `SHA256` together, then running the installer again. Keep the prior
versioned binary available for rollback. The installer restarts the gateway;
run it between active requests.

Enable user-service persistence if needed: `loginctl enable-linger "$USER"`.
The Ubuntu desktop already has lingering enabled. This does not prevent sleep.

To add or reauthorize a personal account, run:

```sh
~/.local/share/cliproxy-personal/cli-proxy-api \
  -config ~/.config/cliproxy-personal/config.yaml -claude-login
```

Complete Anthropic's browser flow on this desktop, using a different browser
profile/private window for each account. Never copy tokens into the repository.

In T3, the provider has driver Claude Code, binary `~/.local/bin/claude`, config
directory `~/.claude-personal`, and these instance environment settings:

- `ANTHROPIC_BASE_URL=http://127.0.0.1:8317`
- `ANTHROPIC_AUTH_TOKEN`: the value of `~/.config/cliproxy-personal/client-key`,
  marked sensitive in T3
- `ANTHROPIC_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN`: empty
- Cloud-provider selector variables: empty (use this gateway)

## Routing

Every five minutes, the quota helper asks CLIProxyAPI to fetch the signed-in
accounts' session and weekly usage from Anthropic. The helper never reads OAuth
tokens: the gateway substitutes `$TOKEN$` internally. This usage endpoint is an
undocumented subscription endpoint, not the Console API-credit balance API.

Available accounts are prioritized by the soonest **weekly** reset, then session
reset. Unknown usage ranks below known available accounts; an exhausted session
or weekly window ranks last. Existing session affinity takes precedence, keeping
active conversations on the same account while it remains usable. Native proxy
cooldowns and failover handle failures between refreshes. Model-specific limits
are left to native failover. Priorities are routing preferences, not spending
caps; the helper does not enable extra usage or change account billing settings.

Priority changes go through the management API's atomic metadata patch instead
of editing auth files or replacing credentials. This avoids a fork and preserves
upstream refresh and affinity behavior. If usage retrieval fails, the account is
marked unknown; expired windows are never assumed replenished. Cached status
marks snapshots older than two refresh periods stale and hides expired windows.
If the gateway is unreachable, the last priorities remain until the next successful
refresh; native failover continues operating.

## Private state

- `~/.config/cliproxy-personal/`: config, client key, and management key; owner only.
- `~/.local/share/cliproxy-personal/auth/`: OAuth credentials; owner only.
- `~/.local/share/cliproxy-personal/quota.json`: usage snapshot, without tokens.
- `~/.claude-personal/`: separate official Claude Code profile.

The management key is powerful: keep it private. Request-body logging is off.
The service runs without elevated privileges, with write access limited to its
private configuration and state directories. Claude request cloaking is disabled;
no custom fingerprint profile or per-account identity override is configured.

Tests: `python3 -B -m unittest discover -s tests -p test_claude_personal_quota.py -v`.
