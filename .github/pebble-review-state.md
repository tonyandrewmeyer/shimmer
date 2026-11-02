# Pebble upstream review state

This file records how far the monthly upstream review has read. It is maintained
by the scheduled "shimmer: monthly Pebble upstream review" cloud routine, which
diffs [canonical/pebble](https://github.com/canonical/pebble) forward from the
ref below and looks for CLI surface that `PebbleCliClient` should grow to keep
parity with `ops.pebble.Client`.

Update `last_reviewed_ref` in the same change that lands a review, and add a row
to the log. Do not hand-edit the log to skip a release: if a release was never
reviewed, leave the ref where it is so the next run picks it up.

    last_reviewed_ref: v1.33.2
    last_reviewed_at: 2026-11-02

## Review log

| Date | Reviewed range | Outcome |
| --- | --- | --- |
| 2026-08-28 | — (baseline) | Routine created; `v1.32.1` taken as the starting point, nothing reviewed yet. |
| 2026-09-02 | `v1.32.1` → `master` @ `5b8cd10` (unreleased; no new tag) | Nothing affecting shimmer: the three commits in the range touch only `.workshop/`, `.gitignore` and `go.mod`/`go.sum`. See [#154](https://github.com/tonyandrewmeyer/shimmer/issues/154). |
| 2026-10-02 | `5b8cd10` → `v1.33.0` | Reviewed and recorded in [#186](https://github.com/tonyandrewmeyer/shimmer/issues/186), but **no PR was opened**, so this ref was never recorded here and the range was re-reviewed on 2026-11-02. |
| 2026-11-02 | `5b8cd10` → `v1.33.2` (re-reviews the 2026-10-02 range) | Nothing in the range breaks shimmer. Fixed the pre-existing CLI error word-wrap bug that made `PathError` vs `APIError` depend on message length (the item [#186](https://github.com/tonyandrewmeyer/shimmer/issues/186) identified but never shipped). See [#231](https://github.com/tonyandrewmeyer/shimmer/issues/231). |
