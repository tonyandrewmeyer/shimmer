# Pebble upstream review state

This file records how far the monthly upstream review has read. It is maintained
by the scheduled "shimmer: monthly Pebble upstream review" cloud routine, which
diffs [canonical/pebble](https://github.com/canonical/pebble) forward from the
ref below and looks for CLI surface that `PebbleCliClient` should grow to keep
parity with `ops.pebble.Client`.

Update `last_reviewed_ref` in the same change that lands a review, and add a row
to the log. Do not hand-edit the log to skip a release: if a release was never
reviewed, leave the ref where it is so the next run picks it up.

    last_reviewed_ref: v1.32.1
    last_reviewed_at: 2026-08-28

## Review log

| Date | Reviewed range | Outcome |
| --- | --- | --- |
| 2026-08-28 | — (baseline) | Routine created; `v1.32.1` taken as the starting point, nothing reviewed yet. |
