<p align="center">
  <img src="https://raw.githubusercontent.com/tonyandrewmeyer/shimmer/main/assets/shimmer-logo.png" alt="Shimmer" width="480">
</p>

# Shimmer — a shiny Pebble client

A 100% compatible, drop-in replacement for `ops.pebble.Client` that drives
[Pebble](https://documentation.ubuntu.com/pebble) through its **CLI** instead of
the unix socket — for environments where the socket isn't reachable (such as a
Rock or a Juju container).

![Shimmer parity demo](demo.gif)

<sub>The same deploy-and-verify routine run over `ops.pebble.Client` (unix
socket, left) and `shimmer.PebbleCliClient` (CLI, right) — identical results.</sub>

## Overview

`PebbleCliClient` implements the same interface as `ops.pebble.Client`: same
method signatures, same return types, same raised exceptions. Under the hood it
translates each call into a `pebble` CLI command, parses the output back into the
same Python objects `ops` returns, and maps CLI errors onto the matching
exceptions. The contract is **parity** — code written against `ops.pebble.Client`
should run unchanged against Shimmer.

## Installation

```bash
# From PyPI
uv pip install pebble-shimmer

# Development version
git clone https://github.com/tonyandrewmeyer/shimmer
cd shimmer
uv pip install -e .
```

## Usage

Construct the client, then use it exactly like `ops.pebble.Client` — the methods,
arguments, return types, and exceptions are the same:

```python
from shimmer import PebbleCliClient as Client

client = Client()
client.replan_services()
for service in client.get_services():
    print(service.name, service.current.value)
```

The whole point is that there's nothing new to learn: the full method surface is
documented by [`ops.pebble.Client`](https://ops.readthedocs.io/en/latest/reference/pebble.html).
Swapping `ops.pebble.Client` for `shimmer.PebbleCliClient` is the only change.

The constructor is where Shimmer differs, since it talks to a binary rather than
a socket:

```python
client = Client(
    socket_path="/var/lib/pebble/default/.pebble.socket",  # sets PEBBLE / PEBBLE_SOCKET
    pebble_binary="/snap/bin/pebble",  # path to the pebble binary (default: "pebble")
    timeout=5.0,  # default per-command timeout in seconds
)
```

`socket_path` doesn't open a socket — it points Shimmer at the daemon by setting
`PEBBLE` (its parent directory) and `PEBBLE_SOCKET` for the CLI. For drop-in
parity the constructor also accepts `opener` and `base_url`, but those only
configure the socket transport, so Shimmer accepts and ignores them. The
`ops.pebble` exceptions are re-exported from `shimmer` for convenience, but they
are the same objects, so `except ops.pebble.APIError` keeps working too.

## Demo and verification

The GIF above is a recording of [`demo.md`](demo.md) — a
[Showboat](https://pypi.org/project/showboat/) document that runs one
deploy-and-verify routine against the **real socket client**, then the **same
code** against Shimmer, and `diff`s the two outputs to prove they're identical.
It's reproducible:

```bash
uv run python demo.py            # rebuild demo.md (verifies parity live)
uv run python demo.py --record   # re-record demo.cast (needs tmux + asciinema)
agg demo.cast demo.gif           # regenerate the GIF from the cast
```

Parity is also exercised in CI by `tests/integration/test_parity.py`, which runs
the same operations through both clients and asserts equal results.

## Limitations and parity notes

CLI invocation is the source of every limitation here — each call spawns a
`pebble` process, so there's more per-call overhead than the socket transport,
and some streaming is buffered rather than incremental.

A few methods can't fully match the socket client yet:

- `replan_services()`, `start_services()`, `stop_services()`, and
  `restart_services()` return the change ID only when no timeout is set.
- `notify()` supports custom notices only.
- `autostart_services()` is currently an alias for `replan()`.
- `ack_warnings()` is not yet implemented.
- `get_warnings()` is implemented for the "no warnings" case only; parsing a
  non-empty list raises `NotImplementedError`.

`get_services()`, `get_checks()`, `list_files()`, `get_changes()`,
`get_change()`, and `get_identities()` use Pebble's structured `--format json`
output, so they return the same rich data as `ops.pebble.Client` (change
`kind`/`tasks`/`err`, check thresholds, real file ownership, local identity user
IDs). This requires a Pebble build that supports `--format` on read commands.

## Comparison with `ops.pebble.Client`

| | `ops.pebble.Client` | `PebbleCliClient` |
|---|---|---|
| Transport | Unix socket | `pebble` CLI |
| Requires | Socket access | `pebble` binary |
| Performance | Higher | Moderate (per-call process spawn) |
| API | Native | 100% compatible |

## Troubleshooting

**`Pebble binary not found`** — pass the full path:
`Client(pebble_binary="/snap/bin/pebble")`.

**`Connection error`** — confirm the daemon is up and `PEBBLE` points at its home
directory (or pass `socket_path=`); check `pebble version`.

**See the commands Shimmer runs** — enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## More

- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution guidelines
- [CHANGELOG.md](CHANGELOG.md) — version history
- Related: [ops](https://ops.readthedocs.io) ·
  [pebble](https://documentation.ubuntu.com/pebble) · [juju](https://juju.is) ·
  [charmcraft](https://canonical-charmcraft.readthedocs-hosted.com) ·
  [rockcraft](https://documentation.ubuntu.com/rockcraft)
