#! /usr/bin/env python

"""Unit tests for Shimmer - Pebble CLI Client."""

import inspect
import io
import json
import subprocess
from unittest.mock import Mock, patch

import ops
import pytest

from shimmer import ExecProcess, PebbleCliClient


class TestPebbleCliClient:
    """Test cases for PebbleCliClient class."""

    @pytest.fixture
    def mock_subprocess(self):
        """Mock subprocess for testing."""
        with patch("shimmer._client.subprocess") as mock_sub:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_sub.run.return_value = mock_result
            mock_sub.TimeoutExpired = subprocess.TimeoutExpired
            mock_sub.CalledProcessError = subprocess.CalledProcessError
            yield mock_sub

    @pytest.fixture
    def client(self):
        """Create a test client instance."""
        return PebbleCliClient(pebble_binary="mock-pebble")

    def test_init_default_params(self):
        """Test client initialization with default parameters."""
        client = PebbleCliClient()
        assert client.timeout == 5.0
        assert client.pebble_binary == "pebble"

    def test_init_with_socket_path(self):
        """Test client initialization with socket path."""
        socket_path = "/tmp/test/.pebble.socket"
        client = PebbleCliClient(socket_path=socket_path)

        expected_pebble_dir = "/tmp/test"
        assert client._env["PEBBLE"] == expected_pebble_dir  # type: ignore

    def test_run_command_success(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test successful command execution."""
        mock_subprocess.run.return_value.stdout = "success"

        result = client._run_command(["test", "command"])  # type: ignore

        mock_subprocess.run.assert_called_once()
        assert result.stdout == "success"

    def test_run_command_with_input(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test command execution with input data."""
        mock_subprocess.run.return_value.stdout = "success"

        client._run_command(["test"], input_data="test input")  # type: ignore

        call_args = mock_subprocess.run.call_args
        assert call_args[1]["input"] == "test input"

    def test_run_command_timeout(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test command timeout handling."""
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired("cmd", 5.0)

        with pytest.raises(ops.pebble.TimeoutError):
            client._run_command(["test"])  # type: ignore

    def test_run_command_api_error(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test API error handling."""
        error_response = "Error: Test error"
        mock_subprocess.run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr=error_response
        )

        with pytest.raises(ops.pebble.APIError) as exc_info:
            client._run_command(["test"])  # type: ignore

        assert isinstance(exc_info.value, ops.pebble.APIError)
        assert exc_info.value.message == "Error: Test error"
        assert exc_info.value.code == 1

    def test_run_command_file_not_found(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test handling of missing pebble binary."""
        mock_subprocess.run.side_effect = FileNotFoundError()

        with pytest.raises(ops.pebble.ConnectionError):
            client._run_command(["test"])  # type: ignore

    def test_get_system_info(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting system information."""
        mock_subprocess.run.return_value.stdout = "v1.0.0\n"

        info = client.get_system_info()

        assert info.version == "v1.0.0"
        mock_subprocess.run.assert_called_once_with(
            ["mock-pebble", "version", "--client"],
            input=None,
            capture_output=True,
            text=True,
            timeout=5.0,
            env=client._env,  # type: ignore
            check=True,
        )

    def test_add_layer_string(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test adding a layer from string."""
        layer_yaml = "services:\n  test:\n    command: echo test"

        client.add_layer("test-layer", layer_yaml)

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args[:3] == ["mock-pebble", "add", "test-layer"]
        assert call_args[3].endswith(".yaml")

    def test_add_layer_with_combine(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test adding a layer with combine option."""
        layer_yaml = "services:\n  test:\n    command: echo test"

        client.add_layer("test-layer", layer_yaml, combine=True)

        call_args = mock_subprocess.run.call_args[0][0]
        assert "--combine" in call_args

    def test_get_plan(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting the current plan."""
        plan_data = {
            "services": {"test": {"command": "echo test"}},
            "checks": {},
            "log-targets": {},
        }
        mock_subprocess.run.return_value.stdout = json.dumps(plan_data)

        plan = client.get_plan()

        assert plan.services == plan_data["services"]
        assert plan.checks == plan_data["checks"]
        assert plan.log_targets == plan_data["log-targets"]

    def test_replan_services(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test replanning services."""
        mock_subprocess.run.return_value.stdout = "Change 42 completed"

        change_id = client.replan_services()

        assert change_id == ops.pebble.ChangeID("?")
        mock_subprocess.run.assert_called_once_with(
            ["mock-pebble", "replan"],
            input=None,
            capture_output=True,
            text=True,
            timeout=5.0,
            env=client._env,  # type: ignore
            check=True,
        )

    def test_replan_services_no_wait(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test replanning services with no wait."""
        mock_subprocess.run.return_value.stdout = "Change 42 submitted"

        client.replan_services(timeout=0)

        call_args = mock_subprocess.run.call_args[0][0]
        assert "--no-wait" in call_args

    def test_get_services(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting services."""
        text_output = """Service  Startup   Current  Since
service1 enabled  active  2025-07-12T06:55:57Z
service2 disabled inactive  2025-07-12T06:55:57Z"""
        mock_subprocess.run.return_value.stdout = text_output

        services = client.get_services()

        assert len(services) == 2
        assert services[0].name == "service1"
        assert services[0].startup == "enabled"
        assert services[0].current == "active"
        assert services[1].name == "service2"
        assert services[1].startup == "disabled"
        assert services[1].current == "inactive"

    def test_get_services_filtered(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test getting specific services by name."""
        text_output = """Service  Startup   Current  Since
service1 enabled  active  2025-07-12T06:55:57Z
service2 disabled inactive  2025-07-12T06:55:57Z"""
        mock_subprocess.run.return_value.stdout = text_output

        services = client.get_services(names=["service1"])

        assert len(services) == 1
        assert services[0].name == "service1"

    def test_start_services(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test starting services."""
        mock_subprocess.run.return_value.stdout = "Change 42 completed"

        change_id = client.start_services(["service1", "service2"])

        assert change_id == ops.pebble.ChangeID("?")
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "start", "service1", "service2"]

    def test_start_services_empty_list(self, client: PebbleCliClient):
        """Test starting services with empty list raises error."""
        with pytest.raises(ValueError, match="services list cannot be empty"):
            client.start_services([])

    def test_stop_services(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test stopping services."""
        mock_subprocess.run.return_value.stdout = "Change 42 completed"

        change_id = client.stop_services(["service1"])

        assert change_id == ops.pebble.ChangeID("?")
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "stop", "service1"]

    def test_restart_services(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test restarting services."""
        mock_subprocess.run.return_value.stdout = "Change 42 completed"

        change_id = client.restart_services(["service1"])

        assert change_id == ops.pebble.ChangeID("?")
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "restart", "service1"]

    def test_send_signal_string(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test sending signal by string name."""
        client.send_signal("SIGHUP", ["service1"])

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "signal", "HUP", "service1"]

    def test_send_signal_int(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test sending signal by number."""
        import signal

        client.send_signal(signal.SIGTERM, ["service1"])

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "signal", "TERM", "service1"]

    def test_get_checks(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting check status."""
        text_output = """Check     Level  Status
check1    alive  up
check2    ready  down"""
        mock_subprocess.run.return_value.stdout = text_output

        checks = client.get_checks()

        assert len(checks) == 2
        assert checks[0].name == "check1"
        assert checks[0].level == "alive"
        assert checks[0].status == "up"

    def test_get_checks_with_level(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test getting checks filtered by level."""
        mock_subprocess.run.return_value.stdout = "Check Level Status\n"

        client.get_checks(level=ops.pebble.CheckLevel.ALIVE)

        call_args = mock_subprocess.run.call_args[0][0]
        assert "--level" in call_args
        assert "alive" in call_args

    def test_start_checks(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test starting checks."""
        started = client.start_checks(["check1", "check2"])

        assert started == ["check1", "check2"]
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "start-checks", "check1", "check2"]

    def test_stop_checks(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test stopping checks."""
        stopped = client.stop_checks(["check1"])

        assert stopped == ["check1"]
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "stop-checks", "check1"]

    def test_list_files(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test listing files."""
        text_output = """
drwxr-xr-x  root  root       -  2024-02-26T12:58:31Z  bin
-rw-------  ubuntu  ubuntu   811kB  2025-07-12T09:15:20Z  .pebble.state
""".strip()
        mock_subprocess.run.return_value.stdout = text_output

        files = client.list_files("/path")

        assert len(files) == 2
        assert files[0].name == "bin"
        assert files[0].permissions == 0o755
        assert files[0].user == "root"
        assert files[0].group == "root"
        assert files[1].name == ".pebble.state"
        assert files[1].permissions == 0o0600
        assert files[1].user == "ubuntu"
        assert files[1].group == "ubuntu"

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "ls", "--abs-time", "-l", "/path"]

    def test_list_files_with_pattern(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test listing files with pattern."""
        text_output = """
drwxr-xr-x  root  root       -  2024-02-26T12:58:31Z  bin
-rw-------  ubuntu  ubuntu   811kB  2025-07-12T09:15:20Z  .pebble.txt
""".strip()
        mock_subprocess.run.return_value.stdout = text_output

        files = client.list_files("/path", pattern="*.txt")

        assert len(files) == 1
        assert files[0].name == ".pebble.txt"

    def test_make_dir(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test creating directory."""
        client.make_dir("/path/newdir", make_parents=True, permissions=0o755)

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args[:3] == ["mock-pebble", "mkdir", "/path/newdir"]
        assert "-p" in call_args
        assert "-m" in call_args

    def test_remove_path(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test removing path."""
        client.remove_path("/path/file", recursive=True)

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "rm", "/path/file", "--recursive"]

    def test_pull_text(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test pulling file as text."""
        with (
            patch("tempfile.NamedTemporaryFile") as mock_temp,
            patch("builtins.open", create=True) as mock_open,
        ):
            mock_file = Mock()
            mock_file.name = "/tmp/test"
            mock_temp.return_value.__enter__.return_value = mock_file
            mock_file.read.return_value = "file content"
            mock_file.write.return_value = None
            mock_open.return_value.__enter__.return_value = mock_file

            result = client.pull("/path/file")

        assert isinstance(result, io.StringIO)
        assert result.read() == "file content"

    def test_pull_binary(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test pulling file as binary."""
        with (
            patch("tempfile.NamedTemporaryFile") as mock_temp,
            patch("builtins.open", create=True) as mock_open,
        ):
            mock_file = Mock()
            mock_file.name = "/tmp/test"
            mock_temp.return_value.__enter__.return_value = mock_file
            mock_file.read.return_value = b"binary file content"
            mock_file.write.return_value = None
            mock_open.return_value.__enter__.return_value = mock_file

            result = client.pull("/path/file", encoding=None)

        assert isinstance(result, io.BytesIO)
        assert result.read() == b"binary file content"

    def test_push_string(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test pushing string content."""
        with patch("tempfile.NamedTemporaryFile") as mock_temp:
            mock_file = Mock()
            mock_file.name = "/tmp/test"
            mock_temp.return_value.__enter__.return_value = mock_file

            client.push("/path/file", "content", make_dirs=True)

        mock_file.write.assert_called_once()
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "push", "/tmp/test", "/path/file", "-p"]

    def test_exec_simple(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test simple command execution."""
        mock_popen = Mock()
        mock_subprocess.Popen.return_value = mock_popen

        process = client.exec(["echo", "hello"])

        assert isinstance(process, ExecProcess)
        assert process.command == ["echo", "hello"]

    def test_exec_with_options(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test command execution with options."""
        mock_popen = Mock()
        mock_subprocess.Popen.return_value = mock_popen

        client.exec(
            ["echo", "hello"],
            service_context="myservice",
            environment={"VAR": "value"},
            working_dir="/tmp",
            timeout=10.0,
            user="testuser",
        )

        call_args = mock_subprocess.Popen.call_args[0][0]
        assert "--context" in call_args
        assert "myservice" in call_args
        assert "--env" in call_args
        assert "VAR=value" in call_args
        assert "-w" in call_args
        assert "/tmp" in call_args
        assert "--timeout" in call_args
        assert "10.0s" in call_args
        assert "--user" in call_args
        assert "testuser" in call_args

    def test_get_changes(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting changes."""
        text_output = """
ID   Status  Spawn                 Ready                 Summary
1    Error   2025-07-12T06:49:22Z  2025-07-12T06:50:52Z  Perform HTTP check "demo-health"
2    Done    2025-07-12T06:49:22Z  2025-07-12T06:49:22Z  Execute command "echo"
""".strip()
        mock_subprocess.run.return_value.stdout = text_output

        changes = client.get_changes()

        assert len(changes) == 2
        assert changes[0].id == "1"
        assert changes[0].status == "Error"
        assert changes[0].summary == 'Perform HTTP check "demo-health"'
        assert changes[1].id == "2"
        assert changes[1].status == "Done"
        assert changes[1].summary == 'Execute command "echo"'

    def test_get_notices(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting notices."""
        text_output = """
ID   User    Type           Key                    First                 Repeated              Occurrences
89   public  change-update  87                     2025-07-16T03:08:13Z  2025-07-16T03:08:13Z  3
42   1000    custom         demo.example.com/test  2025-07-12T07:08:09Z  2025-07-16T03:08:13Z  10
""".strip()
        mock_subprocess.run.return_value.stdout = text_output

        notices = client.get_notices()

        assert len(notices) == 2
        assert notices[0].id == "89"
        assert notices[0].type == "change-update"
        assert notices[0].key == "87"
        assert notices[0].user_id is None
        assert notices[0].occurrences == 3
        assert notices[1].id == "42"
        assert notices[1].type == "custom"
        assert notices[1].key == "demo.example.com/test"
        assert notices[1].user_id == 1000
        assert notices[1].occurrences == 10

    def test_notify(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test creating a notice."""
        mock_subprocess.run.return_value.stdout = "Recorded notice 90"

        notice_id = client.notify(
            ops.pebble.NoticeType.CUSTOM, "test.example/key", data={"msg": "test"}
        )

        assert notice_id == "90"
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "notify", "test.example/key", "msg=test"]

    def test_get_identities(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting identities."""
        text_output = """
Name     Access   Types
alice    admin    basic
bob      metrics  local
charlie  read     basic,local""".strip()
        mock_subprocess.run.return_value.stdout = text_output

        identities = client.get_identities()

        assert len(identities) == 3
        assert "alice" in identities
        assert identities["alice"].access == "admin"
        assert identities["alice"].basic is not None
        assert identities["alice"].basic.password == "*****"
        assert identities["alice"].local is None
        assert identities["bob"].access == "metrics"
        assert identities["bob"].basic is None
        assert identities["bob"].local is not None
        assert identities["charlie"].access == "read"
        assert identities["charlie"].basic is not None
        assert identities["charlie"].basic.password == "*****"
        assert identities["charlie"].local is not None


class TestCompatibilityWithOpsPebble:
    """Tests to ensure compatibility with ops.pebble.Client interface."""

    @pytest.fixture
    def client(self):
        """Create a client for compatibility testing."""
        return PebbleCliClient(pebble_binary="echo")  # Use echo as mock pebble

    def test_has_all_required_methods(self, client: PebbleCliClient):
        """Test that client has all the required methods from ops.pebble.Client."""
        required_methods = [
            "get_system_info",
            "add_layer",
            "get_plan",
            "replan_services",
            "get_services",
            "start_services",
            "stop_services",
            "restart_services",
            "autostart_services",
            "send_signal",
            "get_checks",
            "start_checks",
            "stop_checks",
            "list_files",
            "make_dir",
            "remove_path",
            "pull",
            "push",
            "exec",
            "get_changes",
            "wait_change",
            "get_notices",
            "get_notice",
            "notify",
            "get_warnings",
            "ack_warnings",
            "get_identities",
            "replace_identities",
            "remove_identities",
        ]

        for method in required_methods:
            assert hasattr(client, method), f"Missing method: {method}"
            assert callable(getattr(client, method)), f"Method not callable: {method}"

    def test_method_signatures_compatible(self, client: PebbleCliClient):
        """Test that method signatures are compatible with ops.pebble.Client."""

        # Test a few key methods have compatible signatures
        exec_sig = inspect.signature(client.exec)
        exec_params = list(exec_sig.parameters.keys())

        expected_exec_params = [
            "command",
            "service_context",
            "environment",
            "working_dir",
            "timeout",
            "user_id",
            "user",
            "group_id",
            "group",
            "stdin",
            "stdout",
            "stderr",
            "encoding",
            "combine_stderr",
        ]

        for param in expected_exec_params:
            assert param in exec_params, f"Missing parameter in exec(): {param}"

    @patch("shimmer._process.subprocess.run")
    def test_error_handling_compatibility(
        self, mock_run: Mock, client: PebbleCliClient
    ):
        """Test that errors are raised in a compatible way."""
        mock_run.side_effect = subprocess.CalledProcessError(
            404, "cmd", stderr='{"result": {"message": "Not found"}}'
        )

        with pytest.raises(ops.pebble.APIError) as exc_info:
            client.get_system_info()

        assert isinstance(exc_info.value, ops.pebble.APIError)
        assert exc_info.value.code == 404
        assert "Not found" in str(exc_info.value.message)

        mock_run.side_effect = FileNotFoundError()

        with pytest.raises(ops.pebble.ConnectionError):
            client.get_system_info()

        mock_run.side_effect = subprocess.TimeoutExpired("cmd", 5.0)

        with pytest.raises(ops.pebble.TimeoutError):
            client.get_system_info()


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.fixture
    def client(self):
        """Create a test client."""
        return PebbleCliClient(pebble_binary="mock-pebble")

    def test_empty_service_lists(self, client: PebbleCliClient):
        """Test methods with empty service lists."""
        with pytest.raises(ValueError):
            client.start_services([])

        with pytest.raises(ValueError):
            client.stop_services([])

        with pytest.raises(ValueError):
            client.restart_services([])

        with pytest.raises(ValueError):
            client.send_signal("TERM", [])

    def test_empty_check_lists(self, client: PebbleCliClient):
        """Test methods with empty check lists."""
        with pytest.raises(ValueError):
            client.start_checks([])

        with pytest.raises(ValueError):
            client.stop_checks([])

    @patch("shimmer._process.subprocess.run")
    def test_malformed_output_parsing(self, mock_run: Mock, client: PebbleCliClient):
        """Test graceful handling of malformed output."""
        mock_run.return_value.stdout = ""

        services = client.get_services()
        assert services == []

        checks = client.get_checks()
        assert checks == []

    def test_file_operations_with_different_types(self, client: PebbleCliClient):
        """Test file operations with different content types."""
        with patch("shimmer._process.subprocess.run") as mock_run:
            mock_run.return_value.stdout = "test content"
            with patch("tempfile.NamedTemporaryFile"):
                client.push("/path/file", "string content")
            with patch("tempfile.NamedTemporaryFile"):
                client.push("/path/file", b"bytes content")
            string_io = io.StringIO("file content")
            with patch("tempfile.NamedTemporaryFile"):
                client.push("/path/file", string_io)


if __name__ == "__main__":
    pytest.main([__file__])
