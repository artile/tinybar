# Fleet validation, 2026-11-01

Platform: macmax, macOS 26.4.1, Apple Silicon.
The first results below apply to version `0.7.0-fleet.1`.

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

## Weekly menu update, 0.7.0-fleet.2

- All 172 Swift tests passed, including three new weekly menu tests.
- The universal arm64 and x86_64 build passed.
- Native light and dark menu images showed two separate account indicators.
- The current feed showed one paused account and one fresh weekly reading.
- The paused account showed `—`, with an orange status light.
- The fresh account showed its weekly percentage left.
- Tests checked weekly selection, model-specific exclusion, missing readings, stale readings, and both account positions.
- The installed app uses this mode by default for Claude proxy accounts.
- Selecting a single pinned limit leaves weekly mode.

## Login recovery fix

- All 14 bridge tests passed, including four new login recovery cases.
- A changed account file or refresh timestamp now clears that account's old retry delay.
- Runtime status changes preserve the delay. A new HTTP 429 starts a new delay.
- After deployment, both live Claude accounts returned fresh weekly limits through the Mac tunnel.
- Tinybar restarted with weekly mode enabled. Native menu rendering showed both percentages.

## Compact menu, 0.7.0-fleet.3

- All 172 Swift tests passed. The universal arm64 and x86_64 build passed.
- Weekly menu labels now show percentages without account number prefixes.
- The client stores the preferred account order by stable ID.
