# Read Claude account limits through a server bridge

The Fleet fork needs several Claude accounts from one CLIProxyAPI server.
The upstream app keys limits and alerts by Provider, which supports only one Claude account.

Use a separate stable account ID for pins and alert cycles.
Keep the local history model keyed by Provider because local logs do not identify the proxy account reliably.
Show this history as combined and omit per-account Plan Value.

Run a small Python bridge beside CLIProxyAPI.
It uses the local management API to list accounts and request each account's usage.
The selected `auth_index` determines the OAuth token on the server.
The bridge does not refresh tokens or request model output.
This keeps the read-only rule in ADR 0001.

Keep the management key on the server.
Return an allowlist of limit fields through a loopback service and an SSH tunnel.
The bridge has no general forwarding route and accepts no mutation methods.
Cache for at least five minutes and preserve provider retry delays.

The Mac app does not start a long-lived child process.
A separate launch agent owns the SSH tunnel, and systemd owns the bridge.
This adds two managed services, but the app keeps its existing poll interval and native UI.

Install the fork as Tinybar Fleet with its own bundle ID.
Disable the upstream updater in Fleet bundles so a Homebrew update cannot replace the fork.
Keep the upstream app available as a separate installation.
