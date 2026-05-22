#! /usr/bin/env python

"""Unit tests for the ExecProcess class"""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import Mock, patch

import ops
import pytest

from shimmer import ExecProcess, PebbleCliClient


class TestPebbleCliExecProcess:
    """Test cases for PebbleCliExecProcess class."""

    @pytest.fixture
    def mock_process(self):
        """Create a mock subprocess.Popen object."""
        process = Mock()
        process.returncode = 0
        process.stdin = Mock()
        process.stdout = Mock()
        process.stderr = Mock()
        return process

    @pytest.fixture
    def client(self):
        """Create a test client instance."""
        return PebbleCliClient(pebble_binary="mock-pebble")

    def test_init(self, mock_process: Mock):
        """Test process initialization."""
        exec_process = ExecProcess(
            command=["echo", "test"],
            process=mock_process,
            encoding="utf-8",
        )

        assert exec_process.command == ["echo", "test"]
        assert exec_process._encoding == "utf-8"  # type: ignore
        assert exec_process.stdin == mock_process.stdin

    def test_wait_success(self, mock_process: Mock):
        """Test successful process wait."""
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        exec_process = ExecProcess(
            command=["echo", "test"],
            process=mock_process,
        )

        exec_process.wait()  # Should not raise
        # wait() must drain the pipes (via communicate) rather than just
        # wait() so it can't deadlock on large output.
        mock_process.communicate.assert_called_once_with(input=None, timeout=None)
        mock_process.wait.assert_not_called()

    def test_wait_failure(self, mock_process: Mock):
        """Test process wait with non-zero exit code."""
        mock_process.communicate.return_value = ("stdout", "stderr")
        mock_process.returncode = 1

        exec_process = ExecProcess(
            command=["false"],
            process=mock_process,
        )

        with pytest.raises(ops.pebble.ExecError) as exc_info:
            exec_process.wait()

        assert isinstance(exc_info.value, ops.pebble.ExecError)
        assert exc_info.value.exit_code == 1
        assert exc_info.value.command == ["false"]
        assert exc_info.value.stdout == "stdout"
        assert exc_info.value.stderr == "stderr"

    def test_wait_feeds_stdin(self, mock_process: Mock):
        """wait() should feed stdin_content to the process."""
        mock_process.communicate.return_value = ("", "")
        mock_process.returncode = 0

        exec_process = ExecProcess(
            command=["cat"],
            process=mock_process,
            stdin_content="hello",
        )

        exec_process.wait()

        mock_process.communicate.assert_called_once_with(input="hello", timeout=None)

    def test_wait_timeout(self, mock_process: Mock):
        """Test process wait timeout."""
        mock_process.communicate.side_effect = [
            subprocess.TimeoutExpired("cmd", 5.0),
            ("", ""),
        ]

        exec_process = ExecProcess(
            command=["sleep", "10"],
            process=mock_process,
            timeout=5.0,
        )

        with pytest.raises(ops.pebble.TimeoutError):
            exec_process.wait()

        mock_process.terminate.assert_called_once()

    def test_wait_output_success(self, mock_process: Mock):
        """Test successful wait_output."""
        mock_process.communicate.return_value = ("stdout", "stderr")
        mock_process.returncode = 0

        exec_process = ExecProcess(
            command=["echo", "test"],
            process=mock_process,
        )

        stdout, stderr = exec_process.wait_output()

        assert stdout == "stdout"
        assert stderr == "stderr"

    def test_wait_output_combine_stderr(self, mock_process: Mock):
        """Test wait_output with combined stderr."""
        mock_process.communicate.return_value = ("stdout", "stderr")
        mock_process.returncode = 0

        exec_process = ExecProcess(
            command=["echo", "test"],
            process=mock_process,
            combine_stderr=True,
        )

        stdout, stderr = exec_process.wait_output()

        assert stdout == "stdoutstderr"
        assert stderr is None

    def test_wait_output_failure(self, mock_process: Mock):
        """Test wait_output with command failure."""
        mock_process.communicate.return_value = ("stdout", "stderr")
        mock_process.returncode = 1

        exec_process = ExecProcess(
            command=["false"],
            process=mock_process,
        )

        with pytest.raises(ops.pebble.ExecError) as exc_info:
            exec_process.wait_output()

        assert isinstance(exc_info.value, ops.pebble.ExecError)
        assert exc_info.value.stdout == "stdout"
        assert exc_info.value.stderr == "stderr"

    def test_send_signal(self, mock_process: Mock):
        """Test sending signal to process."""
        exec_process = ExecProcess(
            command=["sleep", "10"],
            process=mock_process,
        )

        exec_process.send_signal("SIGTERM")

        mock_process.send_signal.assert_called_once()

    def test_send_signal_int(self, mock_process: Mock):
        """Test sending signal by number."""
        import signal

        exec_process = ExecProcess(
            command=["sleep", "10"],
            process=mock_process,
        )

        exec_process.send_signal(signal.SIGTERM)

        mock_process.send_signal.assert_called_once_with(signal.SIGTERM)

    def test_wait_large_output_no_deadlock(self):
        """wait() must not deadlock when output exceeds the OS pipe buffer.

        Regression test: a child writing more than the pipe buffer (~64KB)
        to stdout before exiting will block on write while the parent blocks
        in wait(), unless the pipes are drained concurrently.
        """
        # Emit ~1MB to stdout, well over any pipe buffer, then exit 0.
        process = subprocess.Popen(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * (1024 * 1024))"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        exec_process = ExecProcess(
            command=["big-output"],
            process=process,
            timeout=30.0,
        )

        # Without draining the pipes this call would hang until the timeout.
        exec_process.wait()

        assert process.returncode == 0

    def test_wait_large_output_failure_raises(self):
        """wait() drains large output and still reports ExecError on failure."""
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys; sys.stderr.write('e' * (1024 * 1024)); sys.exit(3)",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        exec_process = ExecProcess(
            command=["big-error"],
            process=process,
            timeout=30.0,
        )

        with pytest.raises(ops.pebble.ExecError) as exc_info:
            exec_process.wait()

        assert exc_info.value.exit_code == 3
        assert len(exc_info.value.stderr) == 1024 * 1024

    @patch("shimmer._process.subprocess.Popen")
    def test_exec_process_edge_cases(self, mock_popen: Mock, client: PebbleCliClient):
        """Test ExecProcess edge cases."""
        mock_process = Mock()
        mock_process.stdin = None
        mock_process.stdout = None
        mock_process.stderr = None
        mock_popen.return_value = mock_process

        # Test with no stdin/stdout/stderr:
        exec_process = client.exec(["echo", "test"])

        assert exec_process.stdin is None
        assert exec_process.stdout is None
        assert exec_process.stderr is None


if __name__ == "__main__":
    pytest.main([__file__])
