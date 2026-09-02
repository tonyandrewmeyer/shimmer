# Pebble upstream review state

This file records how far the monthly upstream review has read. It is maintained
by the scheduled "shimmer: monthly Pebble upstream review" cloud routine, which
diffs [canonical/pebble](https://github.com/canonical/pebble) forward from the
ref below and looks for CLI surface that `PebbleCliClient` should grow to keep
parity with `ops.pebble.Client`.

Update `last_reviewed_ref` in the same change that lands a review, and add a row
to the log. Do not hand-edit the log to skip a release: if a release was never
reviewed, leave the ref where it is so the next run picks it up.

    last_reviewed_ref: 5b8cd1071d8b3ac4fe2c8ae3011fc2b0abef25db
    last_reviewed_at: 2026-09-02

## Review log

| Date | Reviewed range | Outcome |
| --- | --- | --- |
| 2026-08-28 | — (baseline) | Routine created; `v1.32.1` taken as the starting point, nothing reviewed yet. |
| 2026-09-02 | `v1.32.1` → `master` @ `5b8cd10` (unreleased; no new tag) | Nothing affecting shimmer: the three commits in the range touch only `.workshop/`, `.gitignore` and `go.mod`/`go.sum`. See [#154](https://github.com/tonyandrewmeyer/shimmer/issues/154). |
