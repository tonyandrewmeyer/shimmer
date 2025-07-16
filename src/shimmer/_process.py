from __future__ import annotations

import signal
import subprocess
from typing import Any

import ops


class ExecProcess:
    """ExecProcess implementation for CLI-based execution.

    This class mimics the behavior of ops.pebble.ExecProcess but uses
    subprocess for execution instead of websockets.
    """

    def __init__(
        self,
        command: list[str],
        process: subprocess.Popen[Any],
        stdin_content: str | bytes | None = None,
        encoding: str | None = "utf-8",
        combine_stderr: bool = False,
        timeout: float | None = None,
    ):
        self.command = command
        self._process = process
        self._stdin_content = stdin_content
        self._encoding = encoding
        self._combine_stderr = combine_stderr
        self._timeout = timeout
        self._stdout_data: str | bytes | None = None
        self._stderr_data: str | bytes | None = None
        self._finished = False

        # File-like objects for streaming:
        self.stdin = process.stdin if process.stdin else None
        self.stdout = process.stdout if process.stdout else None
        self.stderr = process.stderr if process.stderr and not combine_stderr else None

    def wait(self):
        """Wait for the process to finish."""
        if self._finished:
            return

        try:
            self._process.wait(timeout=self._timeout)
        except subprocess.TimeoutExpired as e:
            self._process.terminate()
            try:
                self._process.wait(timeout=self._timeout)
            except subprocess.TimeoutExpired:
                self._process.kill()
            raise ops.pebble.TimeoutError(
                f"Command {self.command} timed out after {self._timeout}s"
            ) from e
        self._finished = True

        if self._process.returncode == 0:
            return

        stdout_data = ""
        stderr_data = ""

        if self._process.stdout:
            stdout_data = self._process.stdout.read()
            if isinstance(stdout_data, bytes) and self._encoding:
                stdout_data = stdout_data.decode(self._encoding)

        if self._process.stderr:
            stderr_data = self._process.stderr.read()
            if isinstance(stderr_data, bytes) and self._encoding:
                stderr_data = stderr_data.decode(self._encoding)

        raise ops.pebble.ExecError(
            command=self.command,
            exit_code=self._process.returncode,
            stdout=stdout_data,  # type: ignore
            stderr=stderr_data,  # type: ignore
        )

    def wait_output(self) -> tuple[str | bytes, str | bytes | None]:
        """Wait for the process to finish and return (stdout, stderr)."""
        if self._finished and self._stdout_data is not None:
            return self._stdout_data, self._stderr_data

        try:
            stdout_data, stderr_data = self._process.communicate(
                input=self._stdin_content, timeout=self._timeout
            )
        except subprocess.TimeoutExpired as e:
            self._process.kill()
            self._process.wait()
            raise ops.pebble.TimeoutError(
                f"Command {self.command} timed out after {self._timeout}s"
            ) from e

        self._finished = True

        if self._encoding:
            if isinstance(stdout_data, bytes):
                stdout_data = stdout_data.decode(self._encoding)
            if isinstance(stderr_data, bytes):
                stderr_data = stderr_data.decode(self._encoding)

        if self._combine_stderr and stderr_data:
            stdout_data = stdout_data + stderr_data
            stderr_data = None

        self._stdout_data = stdout_data
        self._stderr_data = stderr_data

        if self._process.returncode != 0:
            raise ops.pebble.ExecError(
                command=self.command,
                exit_code=self._process.returncode,
                stdout=stdout_data,
                stderr=stderr_data,
            )

        return stdout_data, stderr_data

    def send_signal(self, sig: int | str):
        """Send signal to the running process."""
        if isinstance(sig, str):
            sig = getattr(signal, sig.upper())
            assert isinstance(sig, int)

        if not self._finished:
            self._process.send_signal(sig)
