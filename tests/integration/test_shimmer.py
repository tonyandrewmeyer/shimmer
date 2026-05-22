#! /usr/bin/env python

"""Shimmer-only integration tests.

Behavioural parity with ops.pebble.Client is covered by test_parity.py. This
module holds the few integration tests that have *no* socket-client equivalent:
failure modes specific to the CLI shim, and performance characteristics of the
CLI path.

These tests run against a real Pebble installation; see conftest.py.
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import time
from collections.abc import Generator

import ops
import pytest

from shimmer import PebbleCliClient

from .conftest import BASE_LAYER

pytestmark = pytest.mark.integration


@pytest.fixture
def temp_pebble_dir() -> Generator[pathlib.Path]:
    """Create a temporary Pebble directory for testing."""
    with tempfile.TemporaryDirectory(prefix="shimmer_test_") as temp_dir:
        pebble_dir = pathlib.Path(temp_dir) / "pebble"
        (pebble_dir / "layers").mkdir(parents=True)
        yield pebble_dir


@pytest.fixture
def pebble_client(pebble_binary: str, temp_pebble_dir: pathlib.Path) -> PebbleCliClient:
    """Create a Shimmer client configured for testing."""
    socket_path = str(temp_pebble_dir / ".pebble.socket")
    return PebbleCliClient(
        socket_path=socket_path,
        pebble_binary=pebble_binary,
        timeout=30.0,
    )


@pytest.fixture
def running_pebble(
    pebble_client: PebbleCliClient, temp_pebble_dir: pathlib.Path
) -> Generator[PebbleCliClient]:
    """Start a single Pebble daemon driven by shimmer, stopped after the test."""
    (temp_pebble_dir / "layers" / "001-test.yaml").write_text(BASE_LAYER)

    pebble_process = None
    try:
        pebble_process = subprocess.Popen(
            [pebble_client.pebble_binary, "run", "--hold"],
            env=pebble_client._env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Probe with a command that actually contacts the daemon (get_services
        # hits the socket); get_system_info only runs `version --client`, which
        # succeeds before the daemon is listening.
        for attempt in range(60):
            try:
                pebble_client.get_services()
                break
            except (ConnectionError, ops.pebble.APIError):
                if attempt == 59:
                    raise
                time.sleep(0.5)

        yield pebble_client
    finally:
        if pebble_process:
            pebble_process.terminate()
            try:
                pebble_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pebble_process.kill()
                pebble_process.wait()


class TestConnectionErrors:
    """Failure modes specific to the CLI shim (no socket-client equivalent)."""

    def test_connection_error_when_binary_missing(self):
        """A non-pebble binary surfaces as a connection/API error, not a crash."""
        client = PebbleCliClient(pebble_binary="/bin/false")
        with pytest.raises((ConnectionError, ops.pebble.APIError)):
            client.get_system_info()


class TestPerformance:
    """Performance characteristics of the CLI path."""

    def test_sequential_operations(self, running_pebble: PebbleCliClient):
        """A handful of operations complete in a reasonable time."""
        start = time.perf_counter()

        running_pebble.get_services()
        running_pebble.get_checks()
        running_pebble.get_changes()
        running_pebble.exec(["echo", "test"]).wait_output()

        duration = time.perf_counter() - start
        assert duration < 10.0
        print(f"4 operations completed in {duration:.2f}s")

    def test_large_file_operations(self, running_pebble: PebbleCliClient):
        """Push/pull of a 1MB file round-trips correctly."""
        large_content = "A" * (1024 * 1024)

        with tempfile.TemporaryDirectory(prefix="shimmer_large_test_") as tmp:
            test_path = pathlib.Path(tmp) / "shimmer_large_test.txt"
            start = time.perf_counter()
            running_pebble.push(str(test_path), large_content)
            read_content = running_pebble.pull(str(test_path)).read()
            duration = time.perf_counter() - start

        assert read_content == large_content
        print(f"1MB file operations completed in {duration:.2f}s")
