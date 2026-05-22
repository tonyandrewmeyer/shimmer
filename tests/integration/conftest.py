#! /usr/bin/env python

"""Shared infrastructure for Shimmer integration tests.

The parity tests in :mod:`test_parity` drive two *independent, identical*
Pebble daemons: one through :class:`ops.pebble.Client` (the real socket client)
and one through :class:`shimmer.PebbleCliClient` (the CLI shim). The same
operation is applied to both and the observable results are compared, so any
behavioural divergence between the socket and CLI paths shows up as a test
failure.

These tests require a real Pebble installation:

1. Pebble binary available in PATH or at ``/snap/bin/pebble``.
2. Permission to create/modify temporary Pebble directories.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import pathlib
import subprocess
import time
from collections.abc import Callable, Generator
from typing import Any

import ops
import pytest

from shimmer import PebbleCliClient

pytestmark = pytest.mark.integration


# The layer both daemons start with. Keeping it identical on both sides is what
# makes the read-back comparisons meaningful.
BASE_LAYER = """\
summary: Test layer for integration tests
description: A simple layer for testing Shimmer
services:
  test-service:
    override: replace
    summary: Test service
    command: sleep 3600
    startup: disabled
checks:
  test-check:
    override: replace
    level: alive
    exec:
      command: echo "healthy"
    period: 10s
    timeout: 3s
"""


# A check-free layer for tests that compare the *change list*: the BASE_LAYER's
# health check spawns recurring `perform-check` changes at slightly different
# wall-clock moments on each daemon, so a change-list snapshot would never match
# byte-for-byte. With no checks, the only changes are the ones the test drives.
CHECKLESS_LAYER = """\
summary: Check-free layer for change-parity tests
services:
  test-service:
    override: replace
    command: sleep 3600
    startup: disabled
"""


def get_pebble_binary() -> str | None:
    """Return the path to a usable pebble binary, or None."""
    candidates = ["pebble", "/snap/bin/pebble"]
    for binary in candidates:
        try:
            # Use --client: a plain `pebble version` does a server check that
            # blocks for ~5s when no daemon is running.
            result = subprocess.run(
                [binary, "version", "--client"], capture_output=True, timeout=10
            )
            if result.returncode == 0:
                return binary
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ):
            continue
    return None


@pytest.fixture(scope="session")
def pebble_binary() -> str:
    """Path to the pebble binary for the session, or skip."""
    pebble = get_pebble_binary()
    if not pebble:
        pytest.skip("Pebble binary not available")
    return pebble


def _start_daemon(
    pebble_binary: str, root: pathlib.Path, layer: str
) -> tuple[subprocess.Popen[bytes], str]:
    """Start a `pebble run --hold` daemon rooted at ``root``.

    Returns the process handle and the socket path it listens on.
    """
    pebble_dir = root / "pebble"
    (pebble_dir / "layers").mkdir(parents=True)
    (pebble_dir / "layers" / "001-test.yaml").write_text(layer)
    socket_path = str(pebble_dir / ".pebble.socket")
    # Reuse PebbleCliClient's env construction so the daemon and the CLI client
    # agree on PEBBLE / PEBBLE_SOCKET.
    env = PebbleCliClient(socket_path=socket_path, pebble_binary=pebble_binary)._env
    process = subprocess.Popen(
        [pebble_binary, "run", "--hold"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process, socket_path


def _wait_ready(client: Any) -> None:
    """Poll until the daemon behind ``client`` is serving on its socket."""
    for attempt in range(60):
        try:
            client.get_services()
            return
        except (ConnectionError, ops.pebble.ConnectionError, ops.pebble.APIError):
            if attempt == 59:
                raise
            time.sleep(0.5)


def _terminate(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


@dataclasses.dataclass
class Twins:
    """A matched pair of clients, each driving its own identical daemon.

    ``socket`` is the reference :class:`ops.pebble.Client`; ``cli`` is the
    :class:`shimmer.PebbleCliClient` under test.
    """

    socket: ops.pebble.Client
    cli: PebbleCliClient

    @property
    def both(self) -> tuple[ops.pebble.Client, PebbleCliClient]:
        return (self.socket, self.cli)


def _twin_daemons(
    pebble_binary: str, tmp_path: pathlib.Path, layer: str
) -> Generator[Twins, None, None]:
    """Boot two identical daemons from ``layer`` and yield matched clients."""
    processes: list[subprocess.Popen[bytes]] = []
    try:
        socket_proc, socket_path = _start_daemon(
            pebble_binary, tmp_path / "socket", layer
        )
        processes.append(socket_proc)
        cli_proc, cli_socket_path = _start_daemon(
            pebble_binary, tmp_path / "cli", layer
        )
        processes.append(cli_proc)

        socket_client = ops.pebble.Client(socket_path=socket_path)
        cli_client = PebbleCliClient(
            socket_path=cli_socket_path,
            pebble_binary=pebble_binary,
            timeout=30.0,
        )

        _wait_ready(socket_client)
        _wait_ready(cli_client)

        yield Twins(socket=socket_client, cli=cli_client)
    finally:
        for process in processes:
            _terminate(process)


@pytest.fixture
def twins(pebble_binary: str, tmp_path: pathlib.Path) -> Generator[Twins, None, None]:
    """Two identical Pebble daemons (with the standard service + check)."""
    yield from _twin_daemons(pebble_binary, tmp_path, BASE_LAYER)


@pytest.fixture
def twins_no_checks(
    pebble_binary: str, tmp_path: pathlib.Path
) -> Generator[Twins, None, None]:
    """Two identical Pebble daemons with no health checks.

    Use for change-list comparisons, where recurring check changes would
    otherwise make snapshots diverge between the two daemons.
    """
    yield from _twin_daemons(pebble_binary, tmp_path, CHECKLESS_LAYER)


# --- Normalisation & comparison ---------------------------------------------

# Fields whose values legitimately differ between two independent daemons (wall
# clock timestamps, durations measured from "now"). They are dropped before
# comparison; their presence/typing is asserted separately where it matters.
VOLATILE_FIELDS = frozenset(
    {
        "current_since",
        "first_occurred",
        "last_occurred",
        "last_repeated",
        "spawn_time",
        "ready_time",
        "last_modified",
        # Task log lines embed wall-clock timestamps, so they never match
        # byte-for-byte between two independently running daemons.
        "log",
    }
)


def normalize(obj: Any, *, drop: frozenset[str] | set[str] = frozenset()) -> Any:
    """Convert an ops.pebble result into a stable, comparable structure.

    Enums become their values, datetimes collapse to a sentinel (so a missing
    vs present timestamp is still caught), and objects become sorted dicts of
    their attributes with volatile and caller-specified fields removed.
    """
    dropped = VOLATILE_FIELDS | set(drop)

    def _n(o: Any) -> Any:
        if isinstance(o, enum.Enum):
            return o.value
        if isinstance(o, datetime.datetime):
            return "<datetime>"
        if isinstance(o, datetime.timedelta):
            return o.total_seconds()
        if isinstance(o, (list, tuple)):
            return [_n(x) for x in o]
        if isinstance(o, dict):
            return {k: _n(v) for k, v in sorted(o.items()) if k not in dropped}
        if hasattr(o, "to_dict"):
            return _n(o.to_dict())
        if hasattr(o, "__dict__"):
            return {k: _n(v) for k, v in sorted(vars(o).items()) if k not in dropped}
        return o

    return _n(obj)


def assert_parity(
    socket_result: Any,
    cli_result: Any,
    *,
    drop: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Assert two results are equal once volatile fields are normalised away."""
    s = normalize(socket_result, drop=drop)
    c = normalize(cli_result, drop=drop)
    assert s == c, f"parity mismatch:\n  socket: {s}\n  cli:    {c}"


def both_results(twins: Twins, op: Callable[[Any], Any]) -> tuple[Any, Any]:
    """Run ``op`` against both clients, returning (socket_result, cli_result)."""
    return op(twins.socket), op(twins.cli)


def capture_exc(client: Any, op: Callable[[Any], Any]) -> BaseException | None:
    """Run ``op(client)`` and return the exception it raised, or None."""
    try:
        op(client)
    except BaseException as exc:  # noqa: BLE001 - we re-inspect the type
        return exc
    return None


def assert_same_exception(
    twins: Twins, op: Callable[[Any], Any]
) -> tuple[BaseException, BaseException]:
    """Assert both clients raise, with the same exception type. Returns both."""
    socket_exc = capture_exc(twins.socket, op)
    cli_exc = capture_exc(twins.cli, op)
    assert socket_exc is not None, "socket client did not raise"
    assert cli_exc is not None, "cli client did not raise"
    assert type(socket_exc) is type(cli_exc), (
        f"exception type mismatch: socket raised {type(socket_exc).__name__}, "
        f"cli raised {type(cli_exc).__name__}"
    )
    return socket_exc, cli_exc


def assert_same_outcome(
    twins: Twins,
    op: Callable[[Any], Any],
    *,
    drop: frozenset[str] | set[str] = frozenset(),
) -> None:
    """Assert ``op`` produces the same outcome on both clients.

    "Same outcome" means: both return (and the values match after
    normalisation), or both raise the same exception type. A return on one side
    and a raise on the other is a mismatch.
    """

    def outcome(client: Any) -> tuple[str, Any]:
        try:
            return ("returned", op(client))
        except BaseException as exc:  # noqa: BLE001
            return ("raised", exc)

    socket_kind, socket_val = outcome(twins.socket)
    cli_kind, cli_val = outcome(twins.cli)
    assert socket_kind == cli_kind, (
        f"outcome mismatch: socket {socket_kind} {socket_val!r}, "
        f"cli {cli_kind} {cli_val!r}"
    )
    if socket_kind == "returned":
        assert_parity(socket_val, cli_val, drop=drop)
    else:
        assert type(socket_val) is type(cli_val), (
            f"exception type mismatch: socket {type(socket_val).__name__}, "
            f"cli {type(cli_val).__name__}"
        )


def wait_until_ready(client: Any, change_id: Any, timeout: float = 15.0) -> None:
    """Poll ``client.get_change(change_id)`` until the change is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if client.get_change(change_id).ready:
            return
        time.sleep(0.2)
    raise AssertionError(f"change {change_id} not ready within {timeout}s")
