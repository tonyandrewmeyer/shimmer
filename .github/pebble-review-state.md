# Pebble upstream review state

This file records how far the monthly upstream review has read. It is maintained
by the scheduled "shimmer: monthly Pebble upstream review" cloud routine, which
diffs [canonical/pebble](https://github.com/canonical/pebble) forward from the
ref below and looks for CLI surface that `PebbleCliClient` should grow to keep
parity with `ops.pebble.Client`.

Update `last_reviewed_ref` in the same change that lands a review, and add a row
to the log. Do not hand-edit the log to skip a release: if a release was never
reviewed, leave the ref where it is so the next run picks it up.

Before trusting any range, check `git rev-parse --is-shallow-repository` in the
pebble checkout. A shallow clone has no tags and answers ancestry questions
wrongly -- `git merge-base` reports no common ancestor and `git tag --contains`
omits tags that really do contain the ref -- which looks exactly like upstream
having rewritten history. `git fetch --unshallow --tags` fixes it.

    last_reviewed_ref: v1.33.0
    last_reviewed_at: 2026-10-02

## Review log

| Date | Reviewed range | Outcome |
| --- | --- | --- |
| 2026-08-28 | — (baseline) | Routine created; `v1.32.1` taken as the starting point, nothing reviewed yet. |
| 2026-09-02 | `v1.32.1` → `master` @ `5b8cd10` (unreleased; no new tag) | Nothing affecting shimmer: the three commits in the range touch only `.workshop/`, `.gitignore` and `go.mod`/`go.sum`. See [#154](https://github.com/tonyandrewmeyer/shimmer/issues/154). |
| 2026-10-02 | `5b8cd10` → `v1.33.0` (52 commits; spans `v1.32.2`) | `v1.33.0` itself breaks nothing — the new `Notes` column on `pebble services` is inert because shimmer reads `--format json`, and the new `outdated` field is not exposed by `ops`. Reviewing it surfaced a pre-existing parsing bug: the CLI word-wraps error messages, corrupting `APIError.message` and making status/`PathError` kind depend on message length — fixed here. `add_layer()` reporting plan-validation failures as 500 instead of 400 is left open. See [#186](https://github.com/tonyandrewmeyer/shimmer/issues/186). |
