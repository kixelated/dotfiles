# Claude proxy

`claude-proxy` runs the stock Claude Code binary through a CLIProxyAPI gateway
that pools personal Max subscriptions. Bare `claude` is never wrapped: it uses
whatever account `claude /login` signed in on that host, including the work
logins on the NixOS hosts. Subscription proxying carries provider-policy risk;
this setup was requested with that risk accepted.

The gateway runs on the Ubuntu desktop. Every other host reaches it over the
tailnet, so the desktop must be awake for those sessions to run.

## Use

- Terminal: `claude-proxy` takes the usual Claude Code arguments. It always uses
  the `~/.claude-proxy` profile and the gateway, whatever provider settings the
  caller passes.
- T3: choose **Claude Proxy**. The default **Claude** provider is stock `claude`.
- Account usage: `claude-proxy-quota.py --status` on the desktop, or T3's
  **Usage → Limits** with a CLIProxyAPI source at `http://127.0.0.1:8317` and the
  management key from `~/.config/cliproxy-proxy/management-key`.
- Refresh now: `systemctl --user start claude-proxy-quota.service`.
- Services: `systemctl --user status cliproxy-proxy.service claude-proxy-quota.timer`.

## Install

On the desktop, run the gateway once:

```sh
python3 bin/install-claude-proxy.py --configure-t3
sudo tailscale serve --bg --tcp 8317 tcp://127.0.0.1:8317
```

The gateway listens on `127.0.0.1:8317`; Tailscale Serve shares that port with the
tailnet only. Requests still need the client key. Undo with
`sudo tailscale serve --tcp=8317 off`.

On every other host (macOS and NixOS included), use the desktop's gateway:

```sh
python3 bin/install-claude-proxy.py --gateway desktop --configure-t3
```

This copies the client key over ssh into `~/.config/cliproxy-proxy/client-key`
and writes `http://desktop:8317` to `~/.config/cliproxy-proxy/base-url`.

Both modes link `~/.local/bin/claude-proxy` to this checkout, create the
`~/.claude-proxy` profile with this checkout's `CLAUDE.md` and skills, and, with
`--configure-t3`, add T3's **Claude Proxy** provider. The provider runs
`claude-proxy`, so it needs no environment variables or secrets in T3.

The gateway installer is separate from `install`. It targets Ubuntu x86_64,
installs a pinned CLIProxyAPI release after verifying its SHA-256, creates private
keys if missing, and enables the user service and quota timer. Re-running it
keeps the configuration, keys and saved logins. To update, change `VERSION` and
`SHA256` together and rerun; the previous versioned binary stays for rollback.
It restarts the gateway, so run it between requests. Enable user-service
persistence if needed: `loginctl enable-linger "$USER"`.

To add or reauthorize an account on the desktop:

```sh
~/.local/share/cliproxy-proxy/cli-proxy-api \
  -config ~/.config/cliproxy-proxy/config.yaml -claude-login
```

Use a different browser profile or private window for each account. Never copy
tokens into the repository.

## Routing

Every five minutes, the quota helper asks CLIProxyAPI to fetch each account's
session and weekly usage from Anthropic. The helper never reads OAuth tokens: the
gateway substitutes `$TOKEN$` internally. This usage endpoint is an undocumented
subscription endpoint, not the Console API-credit balance API.

Available accounts are prioritized by the soonest **weekly** reset, then session
reset. Unknown usage ranks below known available accounts; an exhausted session
or weekly window ranks last. Session affinity keeps active conversations on the
same account while it remains usable, and native cooldowns and failover handle
failures between refreshes. Priorities are routing preferences, not spending
caps; the helper never enables extra usage or changes billing settings.

Priority changes go through the management API's atomic metadata patch, which
preserves upstream refresh and affinity behavior. If usage retrieval fails, the
account is marked unknown; expired windows are never assumed replenished. Cached
status marks snapshots older than two refresh periods stale.

## Private state

- `~/.config/cliproxy-proxy/`: config, client key, management key (desktop), and
  `base-url` (other hosts); owner only.
- `~/.local/share/cliproxy-proxy/auth/`: OAuth credentials, desktop only.
- `~/.local/share/cliproxy-proxy/quota.json`: usage snapshot, without tokens.
- `~/.claude-proxy/`: the proxied Claude Code profile.

The management key is powerful and never leaves the desktop. Request-body logging
is off. The service runs unprivileged, with write access limited to its private
directories. Claude request cloaking is disabled.

Tests: `python3 -B -m unittest tests.test_claude_proxy -v`.
