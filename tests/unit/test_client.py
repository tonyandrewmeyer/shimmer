#! /usr/bin/env python

"""Unit tests for Shimmer - Pebble CLI Client."""

import datetime
import inspect
import io
import json
import os
import subprocess
from unittest.mock import Mock, patch

import ops
import pytest
import yaml
from pytest_mock import MockerFixture

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
        assert client._env["PEBBLE"] == expected_pebble_dir
        assert client._env["PEBBLE_SOCKET"] == socket_path

    def test_run_command_success(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test successful command execution."""
        mock_subprocess.run.return_value.stdout = "success"

        result = client._run_command(["test", "command"])

        mock_subprocess.run.assert_called_once()
        assert result.stdout == "success"

    def test_run_command_with_input(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test command execution with input data."""
        mock_subprocess.run.return_value.stdout = "success"

        client._run_command(["test"], input_data="test input")

        call_args = mock_subprocess.run.call_args
        assert call_args[1]["input"] == "test input"

    def test_run_command_timeout(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test command timeout handling."""
        mock_subprocess.run.side_effect = subprocess.TimeoutExpired("cmd", 5.0)

        with pytest.raises(ops.pebble.TimeoutError):
            client._run_command(["test"])

    def test_run_command_api_error(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """An unclassifiable CLI error maps to a 500 with the stripped message."""
        mock_subprocess.run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr="error: something went wrong"
        )

        with pytest.raises(ops.pebble.APIError) as exc_info:
            client._run_command(["test"])

        err = exc_info.value
        # The "error:" prefix is stripped so the message matches the socket
        # client's, and the process exit code is not leaked as the HTTP status.
        assert err.message == "something went wrong"
        assert err.code == 500
        assert err.status == "Internal Server Error"
        assert err.body == {
            "type": "error",
            "status-code": 500,
            "status": "Internal Server Error",
            "result": {"message": "something went wrong"},
        }

    @pytest.mark.parametrize(
        ("stderr", "code", "status", "message"),
        [
            (
                'error: cannot find change with id "42"',
                404,
                "Not Found",
                'cannot find change with id "42"',
            ),
            (
                "error: stat /no/such: no such file or directory",
                404,
                "Not Found",
                "stat /no/such: no such file or directory",
            ),
            (
                'error: cannot start services: service "x" does not exist',
                400,
                "Bad Request",
                'cannot start services: service "x" does not exist',
            ),
            (
                "error: internal server explosion",
                500,
                "Internal Server Error",
                "internal server explosion",
            ),
        ],
    )
    def test_run_command_api_error_status_mapping(
        self,
        mock_subprocess: Mock,
        client: PebbleCliClient,
        stderr: str,
        code: int,
        status: str,
        message: str,
    ):
        """CLI stderr is classified into the HTTP status the socket client uses."""
        mock_subprocess.run.side_effect = subprocess.CalledProcessError(
            1, "cmd", stderr=stderr
        )

        with pytest.raises(ops.pebble.APIError) as exc_info:
            client._run_command(["test"])

        err = exc_info.value
        assert err.code == code
        assert err.status == status
        assert err.message == message
        assert err.body["result"]["message"] == message
        assert err.body["status-code"] == code

    def test_run_command_api_error_empty_stderr(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """An error with no stderr still produces a usable message."""
        mock_subprocess.run.side_effect = subprocess.CalledProcessError(
            3, "cmd", stderr=""
        )

        with pytest.raises(ops.pebble.APIError) as exc_info:
            client._run_command(["test"])

        assert "code 3" in exc_info.value.message
        assert exc_info.value.code == 500

    def test_run_command_file_not_found(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test handling of missing pebble binary."""
        mock_subprocess.run.side_effect = FileNotFoundError()

        with pytest.raises(ops.pebble.ConnectionError):
            client._run_command(["test"])

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
            env=client._env,
            check=True,
        )

    def test_get_system_info_multiline_output(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Only the first line of `version --client` output is used."""
        mock_subprocess.run.return_value.stdout = "v1.2.3\nextra trailing line\n"

        info = client.get_system_info()

        assert info.version == "v1.2.3"

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

    def test_replan_services(
        self, mock_subprocess: Mock, client: PebbleCliClient, mocker: MockerFixture
    ):
        """Replan captures the real change id (via --no-wait) and waits."""
        mock_subprocess.run.return_value.stdout = "42"
        wait = mocker.patch.object(client, "wait_change")

        change_id = client.replan_services()

        assert change_id == ops.pebble.ChangeID("42")
        wait.assert_called_once()
        assert mock_subprocess.run.call_args[0][0] == [
            "mock-pebble",
            "replan",
            "--no-wait",
        ]

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
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "services": {
                    "service1": {
                        "name": "service1",
                        "startup": "enabled",
                        "current": "active",
                        "current-since": "2025-07-12T06:55:57Z",
                    },
                    "service2": {
                        "name": "service2",
                        "startup": "disabled",
                        "current": "inactive",
                    },
                }
            }
        )

        services = client.get_services()

        assert len(services) == 2
        by_name = {svc.name: svc for svc in services}
        assert by_name["service1"].startup == ops.pebble.ServiceStartup.ENABLED
        assert by_name["service1"].current == ops.pebble.ServiceStatus.ACTIVE
        assert by_name["service2"].startup == ops.pebble.ServiceStartup.DISABLED
        assert by_name["service2"].current == ops.pebble.ServiceStatus.INACTIVE

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "services", "--format", "json"]

    def test_get_services_filtered(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test getting specific services by name."""
        # Pebble does the name filtering itself, so it only returns the match.
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "services": {
                    "service1": {
                        "name": "service1",
                        "startup": "enabled",
                        "current": "active",
                    },
                }
            }
        )

        services = client.get_services(names=["service1"])

        assert len(services) == 1
        assert services[0].name == "service1"

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == [
            "mock-pebble",
            "services",
            "service1",
            "--format",
            "json",
        ]

    def test_start_services(
        self, mock_subprocess: Mock, client: PebbleCliClient, mocker: MockerFixture
    ):
        """Test starting services."""
        mock_subprocess.run.return_value.stdout = "42"
        wait = mocker.patch.object(client, "wait_change")

        change_id = client.start_services(["service1", "service2"])

        assert change_id == ops.pebble.ChangeID("42")
        wait.assert_called_once()
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == [
            "mock-pebble",
            "start",
            "service1",
            "service2",
            "--no-wait",
        ]

    def test_start_services_empty_list(self, client: PebbleCliClient):
        """Test starting services with empty list raises error."""
        with pytest.raises(ValueError, match="services list cannot be empty"):
            client.start_services([])

    def test_stop_services(
        self, mock_subprocess: Mock, client: PebbleCliClient, mocker: MockerFixture
    ):
        """Test stopping services."""
        mock_subprocess.run.return_value.stdout = "42"
        wait = mocker.patch.object(client, "wait_change")

        change_id = client.stop_services(["service1"])

        assert change_id == ops.pebble.ChangeID("42")
        wait.assert_called_once()
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "stop", "service1", "--no-wait"]

    def test_restart_services(
        self, mock_subprocess: Mock, client: PebbleCliClient, mocker: MockerFixture
    ):
        """Test restarting services."""
        mock_subprocess.run.return_value.stdout = "42"
        wait = mocker.patch.object(client, "wait_change")

        change_id = client.restart_services(["service1"])

        assert change_id == ops.pebble.ChangeID("42")
        wait.assert_called_once()
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "restart", "service1", "--no-wait"]

    def test_send_signal_string(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test sending signal by string name."""
        client.send_signal("SIGHUP", ["service1"])

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "signal", "HUP", "service1"]

    def test_send_signal_bare_name(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test sending signal by bare name without the 'SIG' prefix."""
        client.send_signal("HUP", ["service1"])

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "signal", "HUP", "service1"]

    def test_send_signal_lowercase_name(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test sending signal by lowercase name."""
        client.send_signal("sighup", ["service1"])

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "signal", "HUP", "service1"]

    def test_send_signal_invalid_name(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test that an invalid signal name raises ValueError."""
        with pytest.raises(ValueError, match="Invalid signal name"):
            client.send_signal("NOTASIGNAL", ["service1"])

    def test_send_signal_int(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test sending signal by number."""
        import signal

        client.send_signal(signal.SIGTERM, ["service1"])

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "signal", "TERM", "service1"]

    def test_get_checks(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting check status."""
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "checks": {
                    "check1": {
                        "name": "check1",
                        "level": "alive",
                        "status": "up",
                        "successes": 5,
                        "failures": 0,
                        "threshold": 3,
                        "change-id": "1",
                    },
                    "check2": {
                        "name": "check2",
                        "level": "ready",
                        "status": "down",
                        "successes": 0,
                        "failures": 3,
                        "threshold": 3,
                        "change-id": "2",
                    },
                }
            }
        )

        checks = client.get_checks()

        assert len(checks) == 2
        by_name = {check.name: check for check in checks}
        assert by_name["check1"].level == ops.pebble.CheckLevel.ALIVE
        assert by_name["check1"].status == ops.pebble.CheckStatus.UP
        # The JSON format exposes the richer detail that text parsing dropped.
        assert by_name["check1"].successes == 5
        assert by_name["check1"].threshold == 3
        assert by_name["check2"].failures == 3
        assert by_name["check2"].status == ops.pebble.CheckStatus.DOWN

    def test_get_checks_with_level(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test getting checks filtered by level."""
        mock_subprocess.run.return_value.stdout = json.dumps({"checks": {}})

        client.get_checks(level=ops.pebble.CheckLevel.ALIVE)

        call_args = mock_subprocess.run.call_args[0][0]
        assert "--level" in call_args
        assert "alive" in call_args
        assert call_args[-2:] == ["--format", "json"]

    def test_start_checks(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Starting checks returns those that were inactive (now started)."""
        # get_checks (called first) reports both checks inactive.
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "checks": {
                    "check1": {
                        "name": "check1",
                        "status": "inactive",
                        "level": "alive",
                        "threshold": 3,
                    },
                    "check2": {
                        "name": "check2",
                        "status": "inactive",
                        "level": "alive",
                        "threshold": 3,
                    },
                }
            }
        )

        started = client.start_checks(["check1", "check2"])

        assert started == ["check1", "check2"]
        call_args = mock_subprocess.run.call_args[0][0]  # last call: start-checks
        assert call_args == ["mock-pebble", "start-checks", "check1", "check2"]

    def test_stop_checks(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Stopping checks returns those that were running (now stopped)."""
        # get_checks reports check1 running (status up), so stopping it changes it.
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "checks": {
                    "check1": {
                        "name": "check1",
                        "status": "up",
                        "level": "alive",
                        "threshold": 3,
                    }
                }
            }
        )

        stopped = client.stop_checks(["check1"])

        assert stopped == ["check1"]
        call_args = mock_subprocess.run.call_args[0][0]  # last call: stop-checks
        assert call_args == ["mock-pebble", "stop-checks", "check1"]

    def test_list_files(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test listing files."""
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "files": [
                    {
                        "path": "/path/bin",
                        "name": "bin",
                        "type": "directory",
                        "permissions": "755",
                        "last-modified": "2024-02-26T12:58:31Z",
                        "user-id": 0,
                        "user": "root",
                        "group-id": 0,
                        "group": "root",
                    },
                    {
                        "path": "/path/.pebble.state",
                        "name": ".pebble.state",
                        "type": "file",
                        "size": 830464,
                        "permissions": "600",
                        "last-modified": "2025-07-12T09:15:20Z",
                        "user-id": 1000,
                        "user": "ubuntu",
                        "group-id": 1000,
                        "group": "ubuntu",
                    },
                ]
            }
        )

        files = client.list_files("/path")

        assert len(files) == 2
        assert files[0].name == "bin"
        assert files[0].type == ops.pebble.FileType.DIRECTORY
        assert files[0].permissions == 0o755
        assert files[0].user == "root"
        assert files[0].group == "root"
        assert files[1].name == ".pebble.state"
        assert files[1].permissions == 0o0600
        assert files[1].size == 830464
        assert files[1].user == "ubuntu"
        assert files[1].group == "ubuntu"
        # The JSON format provides real numeric IDs (text output had none).
        assert files[1].user_id == 1000
        assert files[1].group_id == 1000

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "ls", "/path", "--format", "json"]

    def test_list_files_with_pattern(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test listing files with pattern."""
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "files": [
                    {
                        "path": "/path/bin",
                        "name": "bin",
                        "type": "directory",
                        "permissions": "755",
                        "last-modified": "2024-02-26T12:58:31Z",
                        "user": "root",
                        "group": "root",
                    },
                    {
                        "path": "/path/.pebble.txt",
                        "name": ".pebble.txt",
                        "type": "file",
                        "size": 12,
                        "permissions": "600",
                        "last-modified": "2025-07-12T09:15:20Z",
                        "user": "ubuntu",
                        "group": "ubuntu",
                    },
                ]
            }
        )

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

    def _pull_writes(self, mock_subprocess: Mock, content: bytes) -> dict:
        """Make the mocked `pebble pull` write ``content`` to its target path.

        ``pull`` runs ``pebble pull <src> <tmp>``; we write to that temp path
        (the last CLI arg) so the returned handle reads real data. Captures the
        temp path so the test can assert it is unlinked afterwards.
        """
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["path"] = cmd[-1]
            with open(cmd[-1], "wb") as fh:
                fh.write(content)
            return Mock(returncode=0, stdout="", stderr="")

        mock_subprocess.run.side_effect = fake_run
        return captured

    def test_pull_text(self, mock_subprocess: Mock, client: PebbleCliClient):
        """pull() returns a readable text handle and cleans up the temp file."""
        captured = self._pull_writes(mock_subprocess, b"file content")

        result = client.pull("/path/file")

        content = result.read()
        assert content == "file content"
        assert isinstance(content, str)
        # The temp file is unlinked immediately; the handle still reads it.
        assert not os.path.exists(captured["path"])
        result.close()

    def test_pull_binary(self, mock_subprocess: Mock, client: PebbleCliClient):
        """pull(encoding=None) returns a readable binary handle."""
        captured = self._pull_writes(mock_subprocess, b"binary file content")

        result = client.pull("/path/file", encoding=None)

        content = result.read()
        assert content == b"binary file content"
        assert isinstance(content, bytes)
        assert not os.path.exists(captured["path"])
        result.close()

    def test_pull_missing_file_raises_path_error_and_cleans_up(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """A failed pull raises PathError and leaves no temp file behind."""
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["path"] = cmd[-1]
            # The real `pebble pull` removes the destination when it fails, so
            # the cleanup path must tolerate the temp file already being gone.
            os.unlink(cmd[-1])
            raise subprocess.CalledProcessError(
                1, "cmd", stderr="error: stat /path/file: no such file or directory"
            )

        mock_subprocess.run.side_effect = fake_run

        with pytest.raises(ops.pebble.PathError) as exc_info:
            client.pull("/path/file")

        assert exc_info.value.kind == "not-found"
        assert not os.path.exists(captured["path"])

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

    @staticmethod
    def _changes_json() -> str:
        return json.dumps(
            {
                "changes": [
                    {
                        "id": "1",
                        "kind": "perform-check",
                        "summary": 'Perform HTTP check "demo-health"',
                        "status": "Error",
                        "tasks": [
                            {
                                "id": "1",
                                "kind": "perform-check",
                                "summary": 'Perform HTTP check "demo-health"',
                                "status": "Error",
                                "progress": {"label": "", "done": 1, "total": 1},
                                "spawn-time": "2025-07-12T06:49:22Z",
                                "ready-time": "2025-07-12T06:50:52Z",
                            }
                        ],
                        "ready": True,
                        "err": 'check "demo-health" failed',
                        "spawn-time": "2025-07-12T06:49:22Z",
                        "ready-time": "2025-07-12T06:50:52Z",
                    },
                    {
                        "id": "2",
                        "kind": "exec",
                        "summary": 'Execute command "echo"',
                        "status": "Doing",
                        "tasks": [],
                        "ready": False,
                        "spawn-time": "2025-07-12T06:49:22Z",
                    },
                ]
            }
        )

    def test_get_changes(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting changes."""
        mock_subprocess.run.return_value.stdout = self._changes_json()

        # Default select is IN_PROGRESS now (matching ops); pass ALL to see both.
        changes = client.get_changes(select=ops.pebble.ChangeState.ALL)

        assert len(changes) == 2
        assert changes[0].id == "1"
        assert changes[0].status == "Error"
        assert changes[0].summary == 'Perform HTTP check "demo-health"'
        # The JSON format restores fields the text parser had to fake.
        assert changes[0].kind == "perform-check"
        assert changes[0].err == 'check "demo-health" failed'
        assert len(changes[0].tasks) == 1
        assert changes[0].tasks[0].kind == "perform-check"
        assert changes[0].ready_time is not None
        assert changes[1].id == "2"
        assert changes[1].kind == "exec"
        assert changes[1].status == "Doing"
        assert changes[1].summary == 'Execute command "echo"'

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "changes", "--format", "json"]

    def test_get_changes_select(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test that the select filter is applied client-side."""
        mock_subprocess.run.return_value.stdout = self._changes_json()
        ready = client.get_changes(select=ops.pebble.ChangeState.READY)
        assert [c.id for c in ready] == ["1"]

        mock_subprocess.run.return_value.stdout = self._changes_json()
        in_progress = client.get_changes(select=ops.pebble.ChangeState.IN_PROGRESS)
        assert [c.id for c in in_progress] == ["2"]

    def test_get_changes_for_service(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """Test that a service filter is passed through as a positional arg."""
        mock_subprocess.run.return_value.stdout = json.dumps({"changes": []})
        client.get_changes(service="demo-server")
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == [
            "mock-pebble",
            "changes",
            "demo-server",
            "--format",
            "json",
        ]

    def test_get_change(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting a single change by ID via the tasks command."""
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "id": "2",
                "kind": "exec",
                "summary": 'Execute command "echo"',
                "status": "Done",
                "tasks": [
                    {
                        "id": "2",
                        "kind": "exec",
                        "summary": 'Execute command "echo"',
                        "status": "Done",
                        "progress": {"label": "", "done": 1, "total": 1},
                        "spawn-time": "2025-07-12T06:49:22Z",
                        "ready-time": "2025-07-12T06:49:23Z",
                    }
                ],
                "ready": True,
                "spawn-time": "2025-07-12T06:49:22Z",
                "ready-time": "2025-07-12T06:49:23Z",
            }
        )

        change = client.get_change(ops.pebble.ChangeID("2"))

        assert change.id == "2"
        assert change.kind == "exec"
        assert len(change.tasks) == 1
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "tasks", "2", "--format", "json"]

    @staticmethod
    def _change_json(*, ready: bool, change_id: str = "2") -> str:
        """Build a `pebble tasks <id> --format json` document."""
        return json.dumps(
            {
                "id": change_id,
                "kind": "exec",
                "summary": "Execute command",
                "status": "Done" if ready else "Doing",
                "tasks": [],
                "ready": ready,
                "spawn-time": "2025-07-12T06:49:22Z",
                "ready-time": "2025-07-12T06:49:23Z" if ready else None,
            }
        )

    def test_wait_change_returns_ready_change(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """wait_change returns immediately when the change is already ready."""
        mock_subprocess.run.return_value.stdout = self._change_json(ready=True)

        change = client.wait_change(ops.pebble.ChangeID("2"), timeout=10.0)

        assert change.id == "2"
        assert change.ready

    def test_wait_change_timeout(self, mock_subprocess: Mock, client: PebbleCliClient):
        """wait_change raises TimeoutError when the change never becomes ready."""
        mock_subprocess.run.return_value.stdout = self._change_json(ready=False)

        with pytest.raises(ops.pebble.TimeoutError, match="timed out"):
            client.wait_change(ops.pebble.ChangeID("2"), timeout=0)

    def test_wait_change_polls_until_ready(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """wait_change keeps polling until the change reports ready."""
        not_ready = Mock(returncode=0, stderr="", stdout=self._change_json(ready=False))
        is_ready = Mock(returncode=0, stderr="", stdout=self._change_json(ready=True))
        mock_subprocess.run.side_effect = [not_ready, not_ready, is_ready]

        with patch("shimmer._client.time.sleep") as mock_sleep:
            change = client.wait_change(
                ops.pebble.ChangeID("2"), timeout=10.0, delay=0.01
            )

        assert change.ready
        assert mock_subprocess.run.call_count == 3
        assert mock_sleep.call_count == 2

    @staticmethod
    def _notice_yaml(
        id: str,
        *,
        user_id: str = "1000",
        type: str = "custom",
        key: str = "example.com/foo",
        occurrences: int = 1,
        with_data: bool = True,
    ) -> str:
        """Build a YAML document matching ``pebble notice <id>`` output."""
        doc = (
            f'id: "{id}"\n'
            f"user-id: {user_id}\n"
            f"type: {type}\n"
            f'key: "{key}"\n'
            "first-occurred: 2025-07-16T03:08:13.5Z\n"
            "last-occurred: 2025-07-16T04:09:14.5Z\n"
            "last-repeated: 2025-07-16T03:08:13.5Z\n"
            f"occurrences: {occurrences}\n"
            "expire-after: 168h0m0s\n"
        )
        if with_data:
            doc += 'last-data:\n    a: "1"\n    b: "2"\n'
        return doc

    def test_get_notices(self, mock_subprocess: Mock, client: PebbleCliClient):
        """get_notices() parses the table for IDs then fetches each in full."""
        table = """
ID   User    Type           Key                    First                 Repeated              Occurrences
89   public  change-update  87                     2025-07-16T03:08:13Z  2025-07-16T03:08:13Z  3
42   1000    custom         demo.example.com/test  2025-07-12T07:08:09Z  2025-07-16T03:08:13Z  10
""".strip()
        mock_subprocess.run.side_effect = [
            Mock(returncode=0, stdout=table, stderr=""),
            Mock(
                returncode=0,
                stdout=self._notice_yaml(
                    "89",
                    user_id="null",  # public notices render user-id as null
                    type="change-update",
                    key="87",
                    occurrences=3,
                ),
                stderr="",
            ),
            Mock(
                returncode=0,
                stdout=self._notice_yaml(
                    "42", key="demo.example.com/test", occurrences=10
                ),
                stderr="",
            ),
        ]

        notices = client.get_notices()

        assert len(notices) == 2
        assert notices[0].id == "89"
        assert notices[0].type == ops.pebble.NoticeType.CHANGE_UPDATE
        assert notices[0].key == "87"
        assert notices[0].user_id is None
        assert notices[0].occurrences == 3
        assert notices[1].id == "42"
        assert notices[1].type == ops.pebble.NoticeType.CUSTOM
        assert notices[1].key == "demo.example.com/test"
        assert notices[1].user_id == 1000
        assert notices[1].occurrences == 10
        # The detail fetch supplies what the table cannot.
        assert notices[1].last_data == {"a": "1", "b": "2"}

    def test_get_notices_empty(self, mock_subprocess: Mock, client: PebbleCliClient):
        """No matching notices returns an empty list without per-ID fetches."""
        mock_subprocess.run.return_value.stdout = "No matching notices."

        assert client.get_notices() == []
        assert mock_subprocess.run.call_count == 1

    def test_get_notice(self, mock_subprocess: Mock, client: PebbleCliClient):
        """get_notice() parses the full YAML document into a typed Notice."""
        mock_subprocess.run.return_value.stdout = self._notice_yaml("12")

        notice = client.get_notice("12")

        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "notice", "12"]
        assert notice.id == "12"
        assert notice.user_id == 1000
        assert notice.type == ops.pebble.NoticeType.CUSTOM
        assert notice.key == "example.com/foo"
        # Timestamps are real datetimes, and last_occurred is the parsed value
        # rather than a fabricated "now".
        assert notice.first_occurred == datetime.datetime(
            2025, 7, 16, 3, 8, 13, 500000, tzinfo=datetime.UTC
        )
        assert notice.last_occurred == datetime.datetime(
            2025, 7, 16, 4, 9, 14, 500000, tzinfo=datetime.UTC
        )
        assert notice.last_data == {"a": "1", "b": "2"}
        assert notice.expire_after == datetime.timedelta(hours=168)

    def test_notify(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test creating a notice."""
        mock_subprocess.run.return_value.stdout = "Recorded notice 90"

        notice_id = client.notify(
            ops.pebble.NoticeType.CUSTOM, "test.example/key", data={"msg": "test"}
        )

        assert notice_id == "90"
        call_args = mock_subprocess.run.call_args[0][0]
        assert call_args == ["mock-pebble", "notify", "test.example/key", "msg=test"]

    def test_notify_repeat_after(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test that repeat_after is rendered as a Pebble duration string."""
        mock_subprocess.run.return_value.stdout = "Recorded notice 91"

        client.notify(
            ops.pebble.NoticeType.CUSTOM,
            "test.example/key",
            repeat_after=datetime.timedelta(minutes=30),
        )

        call_args = mock_subprocess.run.call_args[0][0]
        assert "--repeat-after" in call_args
        # 30 minutes -> "1800.0s", a valid Go duration (not a bare "1800.0").
        assert call_args[call_args.index("--repeat-after") + 1] == "1800.0s"

    def test_notify_non_custom_raises_value_error(self, client: PebbleCliClient):
        """Test that non-custom notice types raise ValueError (not AssertionError)."""
        with pytest.raises(ValueError, match="Only custom notices are supported"):
            client.notify(ops.pebble.NoticeType.CHANGE_UPDATE, "some-key")

    def test_warnings_unsupported(self, client: PebbleCliClient):
        """Warnings are deprecated in Pebble; both methods raise clearly."""
        with pytest.raises(NotImplementedError, match="deprecated"):
            client.get_warnings()
        with pytest.raises(NotImplementedError, match="deprecated"):
            client.ack_warnings(datetime.datetime.now(datetime.UTC))

    def test_abort_change_unsupported(self, client: PebbleCliClient):
        """The CLI has no abort command, so abort_change raises clearly."""
        with pytest.raises(NotImplementedError, match="abort"):
            client.abort_change(ops.pebble.ChangeID("1"))

    def test_get_identities(self, mock_subprocess: Mock, client: PebbleCliClient):
        """Test getting identities."""
        mock_subprocess.run.return_value.stdout = json.dumps(
            {
                "identities": {
                    "alice": {"access": "admin", "basic": {"password": "*****"}},
                    "bob": {"access": "metrics", "local": {"user-id": 1000}},
                    "charlie": {
                        "access": "read",
                        "basic": {"password": "*****"},
                        "local": {"user-id": 1001},
                    },
                }
            }
        )

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
        # The JSON format carries the real local user-id (text output faked it).
        assert identities["bob"].local.user_id == 1000
        assert identities["charlie"].access == "read"
        assert identities["charlie"].basic is not None
        assert identities["charlie"].basic.password == "*****"
        assert identities["charlie"].local is not None
        assert identities["charlie"].local.user_id == 1001

    def _capture_from_file(self, mock_subprocess: Mock) -> dict:
        """Make the mocked CLI capture the YAML written to its ``--from`` file.

        ``replace_identities``/``remove_identities`` write a temp YAML file and
        pass it via ``--from``; the file is deleted when the call returns, so we
        read it back inside the mock to assert on its parsed contents.
        """
        captured: dict = {}

        def fake_run(cmd, **kwargs):
            path = cmd[cmd.index("--from") + 1]
            with open(path) as f:
                captured["data"] = yaml.safe_load(f)
            return Mock(returncode=0, stdout="", stderr="")

        mock_subprocess.run.side_effect = fake_run
        return captured

    def test_replace_identities(self, mock_subprocess: Mock, client: PebbleCliClient):
        """replace_identities writes the identities as YAML and uses --replace."""
        captured = self._capture_from_file(mock_subprocess)

        client.replace_identities(
            {"alice": {"access": "admin", "local": {"user-id": 1000}}}
        )

        cmd = mock_subprocess.run.call_args[0][0]
        assert cmd[:3] == ["mock-pebble", "update-identities", "--from"]
        assert cmd[-1] == "--replace"
        assert captured["data"] == {
            "identities": {"alice": {"access": "admin", "local": {"user-id": 1000}}}
        }

    def test_replace_identities_accepts_identity_objects(
        self, mock_subprocess: Mock, client: PebbleCliClient
    ):
        """An Identity object is serialised via to_dict()."""
        captured = self._capture_from_file(mock_subprocess)

        identity = ops.pebble.Identity.from_dict(
            {"access": "read", "local": {"user-id": 42}}
        )
        client.replace_identities({"bob": identity})

        assert captured["data"]["identities"]["bob"]["access"] == "read"
        assert captured["data"]["identities"]["bob"]["local"]["user-id"] == 42

    def test_remove_identities(self, mock_subprocess: Mock, client: PebbleCliClient):
        """remove_identities maps each name to null and replaces."""
        captured = self._capture_from_file(mock_subprocess)

        client.remove_identities(["alice", "bob"])

        cmd = mock_subprocess.run.call_args[0][0]
        assert cmd[:2] == ["mock-pebble", "update-identities"]
        assert "--replace" in cmd
        assert captured["data"] == {"identities": {"alice": None, "bob": None}}


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
            "get_change",
            "abort_change",
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

    def test_satisfies_pebble_client_protocol(self, client: PebbleCliClient):
        """The client must implement every method of PebbleClientProtocol.

        Derived dynamically from the protocol so a method added there (e.g.
        abort_change) can't silently go unimplemented on PebbleCliClient.
        """
        from shimmer._protocol import PebbleClientProtocol

        protocol_methods = {
            name
            for name in dir(PebbleClientProtocol)
            if not name.startswith("_")
            and callable(getattr(PebbleClientProtocol, name, None))
        }
        assert protocol_methods, "no protocol methods discovered"
        missing = [m for m in sorted(protocol_methods) if not hasattr(client, m)]
        assert not missing, f"client does not satisfy protocol; missing: {missing}"

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
            1, "cmd", stderr='error: cannot find change with id "1"'
        )

        with pytest.raises(ops.pebble.APIError) as exc_info:
            client.get_system_info()

        # Mirrors what ops.pebble.Client would raise for the same not-found
        # error: HTTP 404 (not the process exit code) and the daemon's message.
        assert isinstance(exc_info.value, ops.pebble.APIError)
        assert exc_info.value.code == 404
        assert exc_info.value.status == "Not Found"
        assert exc_info.value.message == 'cannot find change with id "1"'

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
