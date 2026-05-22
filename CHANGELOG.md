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
- `APIError` raised on a CLI failure now mirrors `ops.pebble.Client`: `code`
  is the inferred HTTP status (e.g. `404` for not-found, `400` for bad
  requests) instead of the process exit code, `status` is the matching reason
  phrase, `message` drops the CLI's `error:` prefix so it matches the daemon's
  message verbatim, and `body` uses Pebble's wire format
  (`{"type": "error", "status-code": ..., "result": {"message": ...}}`).
  Errors that can't be classified fall back to `500`. Code that branches on
  `APIError.code` (e.g. `== 404`) now works portably across both clients.
- `abort_change()` now exists on `PebbleCliClient`, so the client implements
  the full `ops.pebble.Client` surface (and its own `PebbleClientProtocol`).
  The Pebble CLI exposes no command to abort a change, so it raises a clear
  `NotImplementedError` explaining the limitation instead of failing with
  `AttributeError`.
- `pull()` now returns a file handle that streams from disk instead of
  buffering the whole file into an in-memory `io.StringIO`/`io.BytesIO`. This
  matches `ops.pebble.Client.pull` (which also returns an open file object over
  an unlinked temp file), so large files no longer require a full extra copy in
  memory. The return value is still a readable text/binary file object.

# 2025-07-25

Add missing overloads on pull() and exec().

# 2025-07-21

Add get_change().

# 2025-07-20

Allow Python 3.11.

# 2025-07-12

Initial alpha version.

