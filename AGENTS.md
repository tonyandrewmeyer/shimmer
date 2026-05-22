# AGENTS.md

Guidance for AI agents (and humans) working in this repo. Keep it short and current.

## What this project is

Shimmer provides `PebbleCliClient`, a **100% drop-in replacement for
`ops.pebble.Client`** that talks to Pebble via the **CLI** instead of the unix
socket (for environments with restricted socket access, e.g. a Rock or Juju
container).

**Prime directive: preserve API parity with `ops.pebble.Client`.** Method
signatures, return types, and raised exceptions must match what `ops` exposes.
When in doubt, check the installed `ops.pebble` and mirror it. Parity is
exercised by `tests/integration/test_parity.py`.

## Keep the CHANGELOG current

`CHANGELOG.md` is curated and **must be updated in the same change as any
user-facing behaviour change.** Entries are grouped under a dated `# YYYY-MM-DD`
header, split into `Features:` and `Bug fixes and packaging:`.

- **Include:** new/changed/removed library behaviour, exceptions, packaging
  (e.g. `py.typed`), and anything that affects published artifacts.
- **Exclude:** CI/tooling-only changes, lint/format churn, and dependency
  bumps (Dependabot action/lib bumps do **not** belong in the changelog).
- Describe the change from the **user's** perspective, not the commit's.

If you land a fix and the changelog wasn't touched, that's a miss — add it.

## Development workflow

- Use **`uv`**. `uv sync --extra dev` for a dev environment.
- **`ty`** is the type checker (not pyright/mypy). **`ruff`** does lint +
  format. Both are pinned in the `dev` extra and run through `tox`/`uv run`, so
  every environment uses identical versions.
- Common commands:
  - `tox -e lint` — ruff check + ruff format --check + ty check
  - `tox -e format` — apply ruff formatting
  - `tox -e unit` — unit tests (no Pebble needed)
  - `tox -e integration` — integration tests (**requires a `pebble` binary**)
- `pre-commit` hooks run the same pinned tools via `uv run`; install with
  `pre-commit install`.

## Testing notes

- Unit tests (`tests/unit/`) mock the CLI and need no Pebble.
- Integration tests (`tests/integration/`) shell out to a real `pebble` binary
  and assert parity against the socket client.
- **Temporary:** CI builds Pebble from `master` because the structured
  `--format json` output the client relies on for some read commands isn't in a
  released Pebble yet. Switch back to `snap install pebble` once a release ships
  it (see the note in `.github/workflows/ci.yaml`).

## CI, merging, and supply chain

- `main` is protected: changes go via **PR**, squash-merge only, and must pass
  `lint`, `test (3.12)`, `test (3.13)`, and `zizmor`. There is no admin bypass.
- Commit messages follow **Conventional Commits** (`fix:`, `feat:`,
  `build(deps):`, `chore:`, `docs:`).
- GitHub Actions are **SHA-pinned by default**; `actions/*`, `github/*` and
  `pypa/*` are allowed to use tag/ref pins (see `.github/zizmor.yml`). zizmor
  enforces this — its config file must be named `zizmor.yml` (it does not
  auto-discover `.yaml`).
- Releases publish to PyPI via OIDC trusted publishing in a gated environment,
  with build-provenance + SBOM attestations.
