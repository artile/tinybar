# Claude accounts from CLIProxyAPI

Tinybar Fleet shows each enabled Claude OAuth account from CLIProxyAPI as a separate card.
Each account has its own limits, pin, stale state, and alerts.
The app keeps the same five-minute poll interval.

Fleet shows each Claude account's weekly percentage left in the menu bar by default.
The indicators follow the card order and use labels such as `1:62%` and `2:35%`.
Hover over the indicators to see the account names.
A missing or stale weekly reading shows `—`.
Turn off **Show each weekly limit in menu bar** to use one pinned or Auto limit.
Clicking a limit to pin it also returns to single-limit mode.

## Data flow

```text
Claude usage API
    ^ GET with the selected account's OAuth token
CLIProxyAPI on the server
    ^ local management API, auth_index selects the account
Tinybar bridge on 127.0.0.1:18767
    ^ SSH tunnel
Tinybar Fleet on the Mac
```

The bridge reads `/v0/management/auth-files` and calls `/v0/management/api-call` for each enabled Claude account.
Every forwarded call uses `GET https://api.anthropic.com/api/oauth/usage`.
The bridge never sends a model prompt, changes an account, or refreshes a token.
CLIProxyAPI continues to own its OAuth logins.

The management key stays on the server in a file with mode `0640`, owned by `root:tinybar-bridge`.
The bridge returns only account labels, stable opaque IDs, observation times, limit fields, and fixed error codes.
It does not return OAuth tokens, management keys, credential paths, or raw upstream errors.
The bridge and the Mac tunnel listen only on loopback.

## Install the bridge

The server needs Python 3.11 or later, systemd, and a running CLIProxyAPI.

1. Copy the `Bridge` directory to the server.
2. Create `/etc/tinybar-bridge` with mode `0700`.
3. Provision the existing CLIProxyAPI management key as `/etc/tinybar-bridge/management.key` on the server.
4. Run `sudo sh Bridge/install.sh`.
5. Check `systemctl is-active tinybar-bridge`.

Do not put the management key in Git or copy it to the Mac.
The installer creates an unprivileged service user and restricts access to the key file.
Edit `/etc/tinybar-bridge/config.toml` if CLIProxyAPI uses a different local port.
The bridge refuses remote management URLs and non-loopback listen addresses.

## Install the Mac app

```sh
python3 Scripts/install-fleet-tunnel.py --ssh-host vps
./Scripts/build-app.sh
ditto 'build/Tinybar Fleet.app' '/Applications/Tinybar Fleet.app'
```

The `vps` SSH alias must work with `BatchMode=yes` before you install the tunnel.
The tunnel starts at login and reconnects after a connection failure.
Its log is `~/Library/Logs/Tinybar Fleet/tunnel.log`.

Start Tinybar Fleet. Open Settings and enable **Use CLIProxyAPI accounts**.
Keep the account service URL as `http://127.0.0.1:18767`.
Press Return after you change the URL.
Enable Claude under Subscriptions if you previously disabled it.

The Fleet bundle ID is `io.tao.tinybar.fleet`.
It has separate settings and does not use the upstream Homebrew updater.
This build uses an ad-hoc signature unless you supply your own signing identity.
The upstream Developer ID signature and notarization do not apply to the fork.

## Limits and history

- A failed account keeps its own last reading and shows a stale message.
- A failed account list marks all previous accounts stale.
- A successful list removes accounts that the server removed or disabled.
- Auto selects across fresh account-wide limits. An explicit pin can retain a stale account.
- A changed label does not change the account ID, pin, or alert cycle.
- The server caches results for at least five minutes and honors account-specific retry delays.
- A manual check can read the cached result. It does not bypass a provider delay.
- Local Claude Code history remains combined across accounts.
- Plan Value does not assign combined local tokens to one proxy account.
- The bridge does not fetch subscription plan names or Banked Resets in this version.

## Read-only response

`GET /v1/claude/accounts` returns JSON because this is the app's wire protocol.
Deployment configuration uses TOML.

```json
{
  "schema_version": 1,
  "accounts": [{
    "id": "stable-opaque-id",
    "label": "Account One",
    "fetched_at": "2030-01-01T00:00:00Z",
    "usage": {
      "five_hour": {"utilization": 25, "resets_at": "2030-01-01T05:00:00Z"}
    }
  }]
}
```

An account failure replaces `usage` with `error.code`.
Codes are `login_expired`, `rate_limited`, and `upstream_error`.
`rate_limited` can include `retry_after_seconds`.
A failed management request returns HTTP 503 with no private error details.
The bridge rejects all mutation methods and exposes no general API forwarding route.

## Test

```sh
swift test
python3 -m unittest discover -s Bridge -v
./Scripts/build-app.sh
```

Use `--snapshot out.png --page claude --redact-projects` for screenshots without account labels or project names.
Add `--limits-only` to skip local history import during a limits snapshot.
Add `--weekly-menubar` to render the live weekly menu indicators in light and dark themes.
See [the validation results](fleet-validation.md) for the tested version.

## Remove

On the Mac, run `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/io.tao.tinybar.fleet-tunnel.plist`.
Remove that plist and the Tinybar Fleet app after it quits.
On the server, run `systemctl disable --now tinybar-bridge` before you remove its files.
These steps do not change CLIProxyAPI or its account files.
