# Fleet validation, 2026-11-01

Platform: macmax, macOS 26.4.1, Apple Silicon.

- All 169 Swift tests passed, including seven new account tests.
- All ten Python bridge tests passed.
- The universal release build passed for arm64 and x86_64.
- Code signature verification passed for the local ad-hoc app bundle.
- Python compile checks, shell syntax checks, plist validation, and `git diff --check` passed.
- The live server bridge and Mac SSH tunnel returned two separate Claude accounts.
- One account returned HTTP 200. One returned HTTP 401 with `authentication_error`.
- The response contained no OAuth tokens, management keys, or `auth_index` values.
- Native light and dark snapshots showed both accounts and the separate stale message.
- Tests checked per-account pins, Auto selection, alerts after state reload, account removal, cache delays, and mutation rejection.
- The installed app ran at 0.0% idle CPU after startup.
- `footprint` reported 20 MB. RSS was about 78 MB, above the upstream specification's 50 MB RSS target.

The native automation tool could not attach to this menu-bar-only app and returned `timeoutReached`.
Visual checks used the app's native snapshot command.
The tests verify pin and alert logic. They do not prove notification delivery through macOS permissions.

The account with HTTP 401 needs a renewed login in CLIProxyAPI.
The fork does not change or refresh that login.
