#! /usr/bin/env python

"""Integration tests for Shimmer.

These tests run against a real Pebble installation and require:

1. Pebble binary available in PATH or specified location
2. Proper permissions to create/modify Pebble directories
3. No other Pebble instance running on the same socket
"""

from __future__ import annotations

import pathlib
import subprocess
import tempfile
import time
from collections.abc import Generator

import ops
import pytest
import yaml

from shimmer import PebbleCliClient


def get_pebble_binary() -> str | None:
    """Get the path to pebble binary."""
    candidates = ["pebble", "/snap/bin/pebble"]
    for binary in candidates:
        try:
            result = subprocess.run([binary, "version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return binary
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue


pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def pebble_binary() -> str:
    """Get pebble binary path for the session."""
    pebble = get_pebble_binary()
    if not pebble:
        pytest.skip("Pebble binary not available")
        return ""
    return pebble


@pytest.fixture
def temp_pebble_dir() -> Generator[pathlib.Path]:
    """Create a temporary Pebble directory for testing."""
    with tempfile.TemporaryDirectory(prefix="shimmer_test_") as temp_dir:
        temp_path = pathlib.Path(temp_dir)
        pebble_dir = temp_path / "pebble"
        pebble_dir.mkdir()

        # Create layers directory.
        layers_dir = pebble_dir / "layers"
        layers_dir.mkdir()

        yield pebble_dir


@pytest.fixture
def pebble_client(pebble_binary: str, temp_pebble_dir: pathlib.Path) -> PebbleCliClient:
    """Create a Shimmer client configured for testing."""
    socket_path = str(temp_pebble_dir / ".pebble.socket")
    client = PebbleCliClient(
        socket_path=socket_path,
        pebble_binary=pebble_binary,
        timeout=30.0,
    )
    return client


@pytest.fixture
def running_pebble(
    pebble_client: PebbleCliClient, temp_pebble_dir: pathlib.Path
) -> Generator[PebbleCliClient]:
    """Start Pebble daemon for testing and ensure it's stopped after."""
    # Create a simple test layer.
    test_layer = """
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

    layers_dir = temp_pebble_dir / "layers"
    test_layer_file = layers_dir / "001-test.yaml"
    test_layer_file.write_text(test_layer)

    # Start pebble daemon in background.
    pebble_process = None
    try:
        pebble_process = subprocess.Popen(
            [pebble_client.pebble_binary, "run", "--hold"],
            env=pebble_client._env,  # type: ignore
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Wait for pebble to start.
        max_attempts = 20
        for attempt in range(max_attempts):
            try:
                pebble_client.get_system_info()
                break
            except (ConnectionError, ops.pebble.APIError):
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.5)

        yield pebble_client

    finally:
        # Ensure pebble process is terminated:
        if pebble_process:
            pebble_process.terminate()
            try:
                pebble_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pebble_process.kill()
                pebble_process.wait()


class TestSystemIntegration:
    """Test basic system integration."""

    def test_system_info(self, running_pebble: PebbleCliClient):
        """Test getting system information from real Pebble."""
        info = running_pebble.get_system_info()

        assert hasattr(info, "version")
        assert isinstance(info.version, str)
        assert len(info.version) > 0
        print(f"Pebble version: {info.version}")

    def test_connection_error_handling(self):
        """Test connection error when Pebble is not running."""
        # Don't use running_pebble fixture - test with stopped Pebble.
        client = PebbleCliClient(pebble_binary="/bin/false")
        with pytest.raises((ConnectionError, ops.pebble.APIError)):
            client.get_system_info()


class TestLayerManagement:
    """Test layer management operations."""

    def test_get_plan(self, running_pebble: PebbleCliClient):
        """Test getting the current plan."""
        plan = running_pebble.get_plan()

        assert hasattr(plan, "services")
        assert hasattr(plan, "checks")

        # Should have our test service.
        assert "test-service" in plan.services
        assert "test-check" in plan.checks

    def test_add_layer_and_replan(self, running_pebble: PebbleCliClient):
        """Test adding a layer and replanning."""
        new_layer = """
summary: Dynamic test layer
services:
  dynamic-service:
    override: replace
    command: echo "dynamic service"
    startup: disabled
"""

        running_pebble.add_layer("dynamic", new_layer)
        change_id = running_pebble.replan_services(timeout=10.0)

        assert isinstance(change_id, str)
        plan = running_pebble.get_plan()
        assert "dynamic-service" in plan.services


class TestServiceManagement:
    """Test service management operations."""

    def test_get_services(self, running_pebble: PebbleCliClient):
        """Test getting service status."""
        services = running_pebble.get_services()

        assert isinstance(services, list)
        assert len(services) > 0

        test_service = None
        for service in services:
            if service.name == "test-service":
                test_service = service
                break
        assert test_service is not None
        assert test_service.startup == "disabled"
        assert test_service.current in ["inactive", "active"]

    @pytest.mark.skip(reason="wait_change not implemented yet")
    def test_service_lifecycle(self, running_pebble: PebbleCliClient):
        """Test starting and stopping services."""
        services = running_pebble.get_services(["test-service"])
        assert len(services) == 1
        initial_status = services[0].current
        if initial_status != "active":
            change_id = running_pebble.start_services(["test-service"])
            assert isinstance(change_id, str)
            change = running_pebble.wait_change(change_id, timeout=10.0)
            assert change.ready
            services = running_pebble.get_services(["test-service"])
            assert services[0].current == "active"
        change_id = running_pebble.stop_services(["test-service"])
        change = running_pebble.wait_change(change_id, timeout=10.0)
        assert change.ready
        services = running_pebble.get_services(["test-service"])
        assert services[0].current == "inactive"

    @staticmethod
    def _get_pid(client: PebbleCliClient, proc_name: str) -> str:
        # Use the file API to verify it has restarted.
        # We'll assume that it is the only process of this name running.
        process = client.exec(["pgrep", proc_name])
        stdout, _ = process.wait_output()
        pid = stdout.strip()
        assert pid.isdigit()
        assert isinstance(pid, str)
        return pid

    def test_restart_service(self, running_pebble: PebbleCliClient):
        """Test restarting a service."""
        running_pebble.start_services(["test-service"])
        time.sleep(1)  # Let it start
        original_pid = self._get_pid(running_pebble, "sleep")
        running_pebble.restart_services(["test-service"], timeout=10.0)
        time.sleep(1)  # Let it restart
        new_pid = self._get_pid(running_pebble, "sleep")
        assert original_pid != new_pid


class TestCommandExecution:
    """Test command execution functionality."""

    def test_simple_exec(self, running_pebble: PebbleCliClient):
        """Test executing a simple command."""
        process = running_pebble.exec(["echo", "hello world"])
        stdout, stderr = process.wait_output()

        assert stdout.strip() == "hello world"
        assert stderr is None or stderr == ""

    def test_exec_with_environment(self, running_pebble: PebbleCliClient):
        """Test command execution with environment variables."""
        process = running_pebble.exec(
            ["sh", "-c", 'echo "TEST_VAR=$TEST_VAR"'],
            environment={"TEST_VAR": "test_value"},
        )
        stdout, _ = process.wait_output()

        assert isinstance(stdout, str)
        assert "TEST_VAR=test_value" in stdout

    def test_exec_with_working_dir(self, running_pebble: PebbleCliClient):
        """Test command execution with working directory."""
        process = running_pebble.exec(["pwd"], working_dir="/tmp")
        stdout, _ = process.wait_output()

        assert stdout.strip() == "/tmp"

    def test_exec_failure(self, running_pebble: PebbleCliClient):
        """Test command execution failure handling."""
        process = running_pebble.exec(["false"])

        with pytest.raises(ops.pebble.ExecError) as exc_info:
            process.wait_output()

        assert isinstance(exc_info.value, ops.pebble.ExecError)
        assert exc_info.value.exit_code != 0
        assert exc_info.value.command == ["false"]

    def test_exec_timeout(self, running_pebble: PebbleCliClient):
        """Test command execution timeout."""
        with pytest.raises((TimeoutError, ops.pebble.ExecError)):
            process = running_pebble.exec(["sleep", "30"], timeout=1.0)
            process.wait_output()

    def test_exec_with_stdin(self, running_pebble: PebbleCliClient):
        """Test command execution with stdin input."""
        process = running_pebble.exec(["cat"], stdin="hello from stdin\n")
        stdout, _ = process.wait_output()

        assert stdout.strip() == "hello from stdin"


class TestFileOperations:
    """Test file operations."""

    def test_file_lifecycle(self, running_pebble: PebbleCliClient):
        """Test complete file operation lifecycle."""
        test_content = "Hello from Shimmer integration test!\n"
        with tempfile.TemporaryDirectory(prefix="shimmer_test_file_") as tmp:
            test_path = pathlib.Path(tmp) / "test_file.txt"
            running_pebble.push(str(test_path), test_content)
            file_obj = running_pebble.pull(str(test_path))
            read_content = file_obj.read()
            assert read_content == test_content
            files = running_pebble.list_files(str(test_path.parent))
            file_names = [f.name for f in files]
            assert pathlib.Path(test_path).name in file_names
            running_pebble.remove_path(str(test_path))
            files = running_pebble.list_files(str(test_path.parent))
            file_names = [f.name for f in files]
            assert pathlib.Path(test_path).name not in file_names

    def test_directory_operations(self, running_pebble: PebbleCliClient):
        """Test directory creation and listing."""
        with tempfile.TemporaryDirectory(prefix="shimmer_test_dir_") as tmp:
            test_dir = pathlib.Path(tmp) / "shimmer_test_dir"
            running_pebble.make_dir(str(test_dir), make_parents=True)
            running_pebble.push(f"{test_dir}/test.txt", "test content")
            files = running_pebble.list_files(str(test_dir))
            assert len(files) >= 1
            file_names = [f.name for f in files]
            assert "test.txt" in file_names

    def test_binary_file_operations(self, running_pebble: PebbleCliClient):
        """Test binary file operations."""
        binary_content = b"\x00\x01\x02\x03\xff\xfe\xfd"
        with tempfile.TemporaryDirectory(prefix="shimmer_binary_test_") as tmp:
            test_path = pathlib.Path(tmp) / "shimmer_binary_test"

            running_pebble.push(str(test_path), binary_content)
            file_obj = running_pebble.pull(str(test_path), encoding=None)
            read_content = file_obj.read()
            assert read_content == binary_content


class TestHealthChecks:
    """Test health check operations."""

    def test_get_checks(self, running_pebble: PebbleCliClient):
        """Test getting check status."""
        checks = running_pebble.get_checks()

        assert isinstance(checks, list)

        # Should have our test check
        test_check = None
        for check in checks:
            if check.name == "test-check":
                test_check = check
                break

        assert test_check is not None
        assert test_check.level in ["alive", "ready"]

    def test_check_lifecycle(self, running_pebble: PebbleCliClient):
        """Test starting and stopping checks."""
        # Get initial check status
        checks = running_pebble.get_checks(names=["test-check"])

        # Start the check
        started = running_pebble.start_checks(["test-check"])
        assert "test-check" in started

        # Wait a moment for check to run
        time.sleep(2)

        # Check status should be updated
        checks = running_pebble.get_checks(names=["test-check"])
        assert len(checks) == 1

        # Stop the check
        stopped = running_pebble.stop_checks(["test-check"])
        assert "test-check" in stopped


class TestChangeManagement:
    """Test change tracking and management."""

    def test_get_changes(self, running_pebble: PebbleCliClient):
        """Test getting change history."""
        running_pebble.start_services(["test-service"])
        changes = running_pebble.get_changes()

        assert isinstance(changes, list)
        assert len(changes) > 0

        change = changes[0]
        assert hasattr(change, "id")
        assert hasattr(change, "kind")
        assert hasattr(change, "status")
        assert hasattr(change, "ready")

    @pytest.mark.skip(reason="wait_change not implemented yet")
    def test_wait_change(self, running_pebble: PebbleCliClient):
        """Test waiting for change completion."""
        change_id = running_pebble.start_services(["test-service"])
        change = running_pebble.wait_change(change_id, timeout=10.0)

        assert change.id == change_id
        assert change.ready


class TestNotices:
    """Test notice operations."""

    def test_custom_notice(self, running_pebble: PebbleCliClient):
        """Test creating and retrieving custom notices."""
        notice_id = running_pebble.notify(
            type=ops.pebble.NoticeType.CUSTOM,
            key="shimmer.test/integration",
            data={"test": "integration", "timestamp": str(time.time())},
        )

        assert isinstance(notice_id, str)

        notices = running_pebble.get_notices()

        test_notice = None
        for notice in notices:
            if notice.key == "shimmer.test/integration":
                test_notice = notice
                break
        assert test_notice is not None
        assert test_notice.type == "custom"


class TestErrorHandling:
    """Test error handling in integration scenarios."""

    def test_invalid_service_operations(self, running_pebble: PebbleCliClient):
        """Test operations on non-existent services."""
        with pytest.raises(ops.pebble.APIError):
            running_pebble.start_services(["nonexistent-service"])

    def test_invalid_file_operations(self, running_pebble: PebbleCliClient):
        """Test operations on non-existent files."""
        with pytest.raises(ops.pebble.APIError):
            running_pebble.pull("/nonexistent/path/file.txt")

    def test_permission_errors(self, running_pebble: PebbleCliClient):
        """Test handling of permission errors."""
        with pytest.raises(ops.pebble.APIError):
            running_pebble.push("/root/restricted_file.txt", "content")


class TestPerformance:
    """Test performance characteristics."""

    def test_concurrent_operations(self, running_pebble: PebbleCliClient):
        """Test multiple operations in sequence."""
        start_time = time.perf_counter_ns()

        # Perform multiple operations
        running_pebble.get_services()
        running_pebble.get_checks()
        running_pebble.get_changes()
        running_pebble.exec(["echo", "test"]).wait_output()

        end_time = time.perf_counter_ns()
        duration = (end_time - start_time) / 1_000_000_000.0  # Convert to seconds

        assert duration < 10.0  # 10 seconds should be plenty
        print(f"4 operations completed in {duration:.2f}s")

    def test_large_file_operations(self, running_pebble: PebbleCliClient):
        """Test operations with larger files."""
        large_content = "A" * (1024 * 1024)

        with tempfile.TemporaryDirectory(prefix="shimmer_large_test_") as tmp:
            test_path = pathlib.Path(tmp) / "shimmer_large_test.txt"
            start_time = time.perf_counter_ns()
            running_pebble.push(str(test_path), large_content)
            file_obj = running_pebble.pull(str(test_path))
            read_content = file_obj.read()
            end_time = time.perf_counter_ns()
            duration = (end_time - start_time) / 1_000_000_000.0  # Convert to seconds

        assert read_content == large_content
        print(f"1MB file operations completed in {duration:.2f}s")


# Utility functions for integration tests
def create_test_layer(
    name: str,
    services: ops.pebble.ServiceDict,
    checks: ops.pebble.CheckDict | None = None,
) -> str:
    """Create a test layer YAML string."""
    layer: ops.pebble.LayerDict = {
        "summary": f"Test layer {name}",
        "description": f"Generated test layer for {name}",
        "services": services,
    }
    if checks:
        layer["checks"] = checks
    return yaml.dump(layer)


def wait_for_service_status(
    client: PebbleCliClient,
    service_name: str,
    expected_status: str,
    timeout: float = 10.0,
) -> bool:
    """Wait for a service to reach expected status."""
    start_time = time.time()

    while time.time() - start_time < timeout:
        services = client.get_services([service_name])
        if services and services[0].current == expected_status:
            return True
        time.sleep(0.5)

    return False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration", "--tb=short"])
