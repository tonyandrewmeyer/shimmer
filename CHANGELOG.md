# 2026-05-22

Use Pebble's structured `--format json` output for read commands
(`get_services`, `get_checks`, `list_files`, `get_changes`, `get_change`,
`get_identities`). This is more robust than scraping human-readable tables and
restores information the text parser had to drop or guess: change `kind`,
`tasks` and `err`; check `successes`/`failures`/`threshold`/`change_id`; real
file `user_id`/`group_id`/`size`/`type`; and identity local `user_id`.

Requires a Pebble build that supports `--format` on read commands.

# 2025-07-25

Add missing overloads on pull() and exec().

# 2025-07-21

Add get_change().

# 2025-07-20

Allow Python 3.11.

# 2025-07-12

Initial alpha version.

