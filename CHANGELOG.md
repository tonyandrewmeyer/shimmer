# 2026-05-22

Features:

Use Pebble's structured `--format json` output for read commands
(`get_services`, `get_checks`, `list_files`, `get_changes`, `get_change`,
`get_identities`). This is more robust than scraping human-readable tables and
restores information the text parser had to drop or guess: change `kind`,
`tasks` and `err`; check `successes`/`failures`/`threshold`/`change_id`; real
file `user_id`/`group_id`/`size`/`type`; and identity local `user_id`.

Requires a Pebble build that supports `--format` on read commands.

Bug fixes and packaging:

- `get_warnings()` now correctly returns an empty list when there are no
  warnings (it previously always raised `NotImplementedError`).
- `notify()` raises `ValueError` (instead of `assert`-ing) for non-custom
  notice types, and renders `repeat_after` as a valid Pebble duration string.
- `socket_path` now also sets the `PEBBLE_SOCKET` environment variable, as
  documented.
- The pebble exception types (`Error`, `APIError`, `ChangeError`,
  `ConnectionError`, `ExecError`, `PathError`, `ProtocolError`, `TimeoutError`)
  can now be imported directly from `shimmer` (e.g. `from shimmer import
  APIError`); previously they had to be imported from `ops.pebble`.
- `get_notice()` and `get_notices()` now return correctly-typed `Notice`
  objects (real `last_occurred`/`last_data`/`expire_after`) parsed from
  Pebble's per-ID YAML. `get_notice(id)` previously returned the wrong notice
  or raised `IndexError`.
- `send_signal()` accepts bare signal names (e.g. `"HUP"`) in addition to the
  `"SIGHUP"` form, matching `ops.pebble.Client`; invalid names raise
  `ValueError`.
- `ExecProcess.wait()` no longer deadlocks when a process emits more than the
  OS pipe buffer (~64KB) before exiting, and now feeds `stdin`. It is
  reimplemented in terms of `communicate()`.
- Ship a `py.typed` marker so downstream type checkers use Shimmer's types.
- `__version__` is derived from the installed package metadata.

# 2025-07-25

Add missing overloads on pull() and exec().

# 2025-07-21

Add get_change().

# 2025-07-20

Allow Python 3.11.

# 2025-07-12

Initial alpha version.

