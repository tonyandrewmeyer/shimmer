"""Shimmer - shiny Pebble client

This module provides a PebbleCliClient class that implements the same interface as
ops.pebble.Client but communicates with Pebble via CLI commands instead of via a
socket.
"""

from __future__ import annotations

import datetime
import fnmatch
import io
import json
import os
import pathlib
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterable, Mapping
from typing import Any, BinaryIO, NoReturn, TextIO, cast, overload

import yaml

# Import all the types and exceptions from ops.pebble for compatibility
from ops.pebble import (
    APIError,
    Change,
    ChangeID,
    ChangeState,
    CheckInfo,
    CheckLevel,
    CheckStatus,
    ConnectionError,
    FileInfo,
    Identity,
    IdentityDict,
    Layer,
    Notice,
    NoticesUsers,
    NoticeType,
    PathError,
    Plan,
    ServiceInfo,
    ServiceStartup,
    SystemInfo,
    TimeoutError,
    Warning,
    WarningState,
)

from ._process import ExecProcess
from ._runner import FileTransferRunner, LocalSubprocessRunner, Runner


class PebbleCliClient:
    """A drop-in replacement for ops.pebble.Client that uses CLI commands.

    This class implements the same interface as ops.pebble.Client but
    communicates with Pebble via CLI commands instead of socket communication.
    """

    def __init__(
        self,
        socket_path: str = "",
        opener: Any = None,
        base_url: str = "http://localhost",
        timeout: float = 5.0,
        pebble_binary: str = "pebble",
        runner: Runner | None = None,
    ):
        # ``opener`` and ``base_url`` are accepted only for signature parity with
        # ops.pebble.Client (so PebbleCliClient is a drop-in). They configure the
        # socket HTTP transport, which the CLI client doesn't use, so they are
        # intentionally accepted-and-ignored.
        self.timeout = timeout
        self.pebble_binary = pebble_binary
        self._runner: Runner = runner if runner is not None else LocalSubprocessRunner()
        self._env = os.environ.copy()
        if socket_path:
            # Mirror the two environment variables the Pebble CLI honours: PEBBLE
            # is the daemon directory and PEBBLE_SOCKET overrides the socket path.
            self._env["PEBBLE"] = str(pathlib.Path(socket_path).parent)
            self._env["PEBBLE_SOCKET"] = socket_path

    def _run_command(
        self,
        cmd: list[str],
        input_data: str | None = None,
        timeout: float | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        """Run a pebble CLI command and return the result."""
        full_cmd = [self.pebble_binary] + cmd

        try:
            result = self._runner.run(
                full_cmd,
                input=input_data,
                timeout=timeout or self.timeout,
                env=self._env,
                check=check,
            )
            return result
        except subprocess.CalledProcessError as e:
            raise self._api_error_from_stderr(e.stderr, e.returncode) from e
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"Command {full_cmd} timed out") from e
        except FileNotFoundError as e:
            raise ConnectionError(
                f"Pebble binary not found: {self.pebble_binary}"
            ) from e

    # Substrings used to recover the HTTP status the *socket* client would have
    # surfaced. The CLI only prints ``error: <message>`` and exits non-zero, so
    # the daemon's HTTP status is lost; we infer it from the message text. These
    # markers mirror the messages the real daemon produces (verified against
    # ops.pebble.Client). Order matters: not-found is checked before bad-request
    # so e.g. "cannot find ..." wins over a stray "exist".
    _NOT_FOUND_MARKERS = ("no such file or directory", "cannot find", "not found")
    _BAD_REQUEST_MARKERS = ("does not exist", "already exists")

    @classmethod
    def _api_error_from_stderr(cls, stderr: str | None, returncode: int) -> APIError:
        """Build an ``APIError`` mirroring ops.pebble.Client as closely as possible.

        The Pebble CLI reports daemon errors as ``error: <message>`` on stderr
        and exits non-zero, without exposing the HTTP status the socket client
        sees. We strip that ``error:`` prefix -- so ``message`` matches the
        socket client's message verbatim -- and infer ``code``/``status`` from
        the text, falling back to ``500`` when the error can't be classified.
        ``body`` is reconstructed in Pebble's API wire format so callers that
        inspect it (e.g. branching on ``code == 404``) see the same shape they
        would from ops.pebble.Client.
        """
        message = (stderr or "").strip()
        if message[:6].lower() == "error:":
            message = message[6:].strip()
        if not message:
            message = f"pebble CLI exited with code {returncode}"

        lowered = message.lower()
        if any(m in lowered for m in cls._NOT_FOUND_MARKERS):
            code, status = 404, "Not Found"
        elif any(m in lowered for m in cls._BAD_REQUEST_MARKERS):
            code, status = 400, "Bad Request"
        else:
            code, status = 500, "Internal Server Error"

        body: dict[str, Any] = {
            "type": "error",
            "status-code": code,
            "status": status,
            "result": {"message": message},
        }
        return APIError(body=body, code=code, status=status, message=message)

    def _run_json(
        self,
        cmd: list[str],
        timeout: float | None = None,
    ) -> Any:
        """Run a read command with ``--format json`` and return parsed JSON.

        The structured output emitted by Pebble's read commands matches the
        wire format produced by the Pebble API, so the result can be passed
        straight to the matching ``ops.pebble`` ``from_dict`` constructor. This
        is both more robust and richer than scraping the human-readable tables
        (which drop fields such as a change's kind, tasks, and error).
        """
        result = self._run_command([*cmd, "--format", "json"], timeout=timeout)
        output = result.stdout.strip()
        if not output:
            return None
        return json.loads(output)

    def get_system_info(self) -> SystemInfo:
        """Get system information."""
        # Requires Pebble >= v1.32.0, which added ``--format json`` to
        # ``pebble version``. Emits ``{"client": ..., "server": ...}``; the
        # ``server`` field is the daemon version, matching what ops.pebble
        # returns from ``/v1/system-info``.
        data = self._run_json(["version"])
        return SystemInfo(version=data["server"])

    def add_layer(
        self,
        label: str,
        layer: str | Layer | dict[str, Any],
        *,
        combine: bool = False,
    ):
        """Add a configuration layer."""
        if hasattr(layer, "to_yaml"):
            assert isinstance(layer, Layer)  # Unpythonic, but makes the linters happy.
            layer_yaml = layer.to_yaml()
        elif isinstance(layer, dict):
            layer_yaml = yaml.dump(layer)
        else:
            layer_yaml = str(layer)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as f:
            f.write(layer_yaml)
            f.flush()
            cmd = ["add", label, f.name]
            if combine:
                cmd.append("--combine")
            self._run_command(cmd)

    def get_plan(self) -> Plan:
        """Get the current configuration plan."""
        result = self._run_command(["plan"])
        return Plan(yaml.safe_load(result.stdout))

    def _run_change_command(self, cmd: list[str], timeout: float) -> ChangeID:
        """Run a change-producing command and return its real change ID.

        ``pebble`` only prints the change ID when invoked with ``--no-wait``
        (when it waits, it prints nothing). To match ops.pebble.Client -- which
        always returns the real change ID -- we always pass ``--no-wait`` to
        capture the ID, then wait for the change ourselves when the caller asked
        us to (``timeout`` greater than zero).
        """
        result = self._run_command([*cmd, "--no-wait"])
        change_id = ChangeID(result.stdout.strip())
        if timeout:
            self.wait_change(change_id, timeout=timeout)
        return change_id

    def replan_services(
        self,
        *,
        timeout: float = 30.0,
        delay: float | None = None,
    ) -> ChangeID:
        """Replan services."""
        if delay is not None:
            time.sleep(delay)
        return self._run_change_command(["replan"], timeout)

    def get_services(self, names: Iterable[str] | None = None) -> list[ServiceInfo]:
        """Get service status information."""
        cmd = ["services"]
        if names:
            cmd.extend(names)
        data = self._run_json(cmd)
        if not data:
            return []
        return [ServiceInfo.from_dict(svc) for svc in data["services"].values()]

    def start_services(
        self,
        services: Iterable[str],
        *,
        timeout: float = 30.0,
        delay: float | None = None,
    ) -> ChangeID:
        """Start services."""
        if delay is not None:
            time.sleep(delay)

        service_list = list(services)
        if not service_list:
            raise ValueError("services list cannot be empty")
        return self._run_change_command(["start", *service_list], timeout)

    def stop_services(
        self,
        services: Iterable[str],
        *,
        timeout: float = 30.0,
        delay: float | None = None,
    ) -> ChangeID:
        """Stop services."""
        if delay is not None:
            time.sleep(delay)

        service_list = list(services)
        if not service_list:
            raise ValueError("services list cannot be empty")
        return self._run_change_command(["stop", *service_list], timeout)

    def restart_services(
        self,
        services: Iterable[str],
        *,
        timeout: float = 30.0,
        delay: float | None = None,
    ) -> ChangeID:
        """Restart services."""
        if delay is not None:
            time.sleep(delay)

        service_list = list(services)
        if not service_list:
            raise ValueError("services list cannot be empty")
        return self._run_change_command(["restart", *service_list], timeout)

    def autostart_services(
        self,
        *,
        timeout: float = 30.0,
        delay: float | None = None,
    ) -> ChangeID:
        """Start all startup-enabled services."""
        # There's no direct CLI equivalent; `replan` starts enabled services.
        # ops.pebble.Client's autostart raises "no default services" when no
        # service is startup-enabled, but `replan` succeeds silently in that
        # case -- so reproduce the error to stay API-compatible.
        plan = self.get_plan()
        enabled = [
            name
            for name, service in plan.services.items()
            if service.startup == ServiceStartup.ENABLED.value
        ]
        if not enabled:
            message = "no default services"
            raise APIError(
                body={"message": message},
                code=400,
                status="Bad Request",
                message=message,
            )
        return self.replan_services(timeout=timeout, delay=delay)

    def send_signal(
        self,
        sig: int | str,
        services: Iterable[str],
    ) -> None:
        """Send signal to services."""
        service_list = list(services)
        if not service_list:
            raise ValueError("services list cannot be empty")

        if isinstance(sig, int):
            sig_name = signal.Signals(sig).name
        else:
            # Accept both "SIGHUP" and the bare "HUP" form (any case).
            full_name = sig.upper()
            if not full_name.startswith("SIG"):
                full_name = "SIG" + full_name
            if full_name not in signal.Signals.__members__:
                raise ValueError(f"Invalid signal name: {sig}")
            sig_name = full_name
        # Pebble's CLI expects the bare, uppercase signal name (e.g. "HUP").
        cmd = ["signal", sig_name[3:]] + service_list
        self._run_command(cmd)

    def get_checks(
        self,
        level: CheckLevel | None = None,
        names: Iterable[str] | None = None,
    ) -> list[CheckInfo]:
        """Get check status information."""
        cmd = ["checks"]
        if level:
            cmd.extend(["--level", level.value])
        if names:
            cmd.extend(names)

        data = self._run_json(cmd)
        if not data:
            return []
        return [CheckInfo.from_dict(check) for check in data["checks"].values()]

    def _inactive_checks(self, names: list[str]) -> set[str]:
        """Names (from ``names``) whose check is currently inactive."""
        return {
            check.name
            for check in self.get_checks(names=names)
            if check.status == CheckStatus.INACTIVE
        }

    def start_checks(self, checks: Iterable[str]) -> list[str]:
        """Start checks, returning those whose state actually changed.

        Like ops.pebble.Client, checks that were already running are not
        included in the result.
        """
        check_list = list(checks)
        if not check_list:
            raise ValueError("checks list cannot be empty")

        # Only inactive checks transition to running, so they are the ones the
        # API reports as changed.
        was_inactive = self._inactive_checks(check_list)
        self._run_command(["start-checks", *check_list])
        return [name for name in check_list if name in was_inactive]

    def stop_checks(self, checks: Iterable[str]) -> list[str]:
        """Stop checks, returning those whose state actually changed.

        Like ops.pebble.Client, checks that were already inactive are not
        included in the result.
        """
        check_list = list(checks)
        if not check_list:
            raise ValueError("checks list cannot be empty")

        # Only running checks transition to inactive, so they are the ones the
        # API reports as changed.
        was_inactive = self._inactive_checks(check_list)
        self._run_command(["stop-checks", *check_list])
        return [name for name in check_list if name not in was_inactive]

    # File operations
    @staticmethod
    def _raise_path_error(error: APIError) -> NoReturn:
        """Translate a file-operation APIError into a PathError.

        ops.pebble.Client raises PathError (not APIError) when a file operation
        fails because of the path itself. We classify the CLI's error text into
        the same ``kind`` values the API uses; anything that isn't a path error
        (e.g. a connection failure) is re-raised unchanged.
        """
        text = (error.message or "").lower()
        if "no such file" in text or "does not exist" in text:
            kind = "not-found"
        elif "permission denied" in text:
            kind = "permission-denied"
        elif (
            "not a directory" in text
            or "is a directory" in text
            or "already exists" in text
        ):
            kind = "generic"
        else:
            raise error
        raise PathError(kind, error.message) from error

    def list_files(
        self,
        path: str,
        *,
        pattern: str | None = None,
        itself: bool = False,
    ) -> list[FileInfo]:
        """List files in a directory."""
        cmd = ["ls", path]
        if itself:
            cmd.append("-d")

        try:
            data = self._run_json(cmd)
        except APIError as e:
            self._raise_path_error(e)
        files = [FileInfo.from_dict(entry) for entry in (data or {}).get("files", [])]
        # ``pattern`` matches against entry names; Pebble's ls glob support only
        # applies to the final path element, so filter here to match the
        # ops.pebble.Client semantics exactly.
        if pattern:
            files = [f for f in files if fnmatch.fnmatch(f.name, pattern)]
        return files

    def make_dir(
        self,
        path: str,
        *,
        make_parents: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ) -> None:
        """Create a directory."""
        cmd = ["mkdir", path]
        if make_parents:
            cmd.append("-p")
        if permissions is not None:
            cmd.extend(["-m", oct(permissions)])
        if user:
            cmd.extend(["--user", user])
        elif user_id is not None:
            cmd.extend(["--uid", str(user_id)])
        if group:
            cmd.extend(["--group", group])
        elif group_id is not None:
            cmd.extend(["--gid", str(group_id)])

        try:
            self._run_command(cmd)
        except APIError as e:
            self._raise_path_error(e)

    def remove_path(self, path: str, *, recursive: bool = False) -> None:
        """Remove a file or directory."""
        cmd = ["rm", path]
        if recursive:
            cmd.append("--recursive")

        try:
            self._run_command(cmd)
        except APIError as e:
            self._raise_path_error(e)

    @overload
    def pull(self, path: str, *, encoding: None) -> BinaryIO: ...

    @overload
    def pull(self, path: str, *, encoding: str = "utf-8") -> TextIO: ...

    def pull(
        self,
        path: str,
        *,
        encoding: str | None = "utf-8",
    ) -> TextIO | BinaryIO:
        """Read a file from the remote system."""
        if hasattr(self._runner, "upload_temp") and hasattr(
            self._runner, "download_temp"
        ):
            return self._pull_via_runner(
                cast(FileTransferRunner, self._runner), path, encoding=encoding
            )
        return self._pull_local(path, encoding=encoding)

    def _pull_via_runner(
        self,
        runner: FileTransferRunner,
        path: str,
        *,
        encoding: str | None,
    ) -> TextIO | BinaryIO:
        """Pull using the runner's file-transfer methods (remote runner path)."""
        tmp_path = runner.upload_temp(b"")
        try:
            self._run_command(["pull", path, tmp_path])
            raw = runner.download_temp(tmp_path)
        except APIError as e:
            self._raise_path_error(e)
        finally:
            runner.cleanup_temp(tmp_path)
        if encoding is None:
            return io.BytesIO(raw)
        return io.StringIO(raw.decode(encoding))

    def _pull_local(
        self,
        path: str,
        *,
        encoding: str | None,
    ) -> TextIO | BinaryIO:
        """Pull via a local temp file (default local-subprocess path).

        The Pebble CLI writes the fetched file to a path, so we pull into a
        temp file, open it, then unlink it immediately: on Unix the open handle
        stays valid until closed, so the data is still readable and the temp
        file is reclaimed when the caller closes it.  This mirrors
        ops.pebble.Client.pull (``newline=""`` serves line endings as-is).
        """
        fd, tmp_name = tempfile.mkstemp()
        os.close(fd)
        # On a failed pull the CLI removes the destination it was given, so all
        # cleanup uses missing_ok to tolerate the temp file already being gone.
        tmp_path = pathlib.Path(tmp_name)
        try:
            self._run_command(["pull", path, tmp_name])
        except APIError as e:
            tmp_path.unlink(missing_ok=True)
            self._raise_path_error(e)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

        handle: TextIO | BinaryIO = (
            open(tmp_name, "rb")
            if encoding is None
            else open(tmp_name, encoding=encoding, newline="")
        )
        tmp_path.unlink(missing_ok=True)
        return handle

    def push(
        self,
        path: str,
        source: str | bytes | TextIO | BinaryIO,
        *,
        encoding: str = "utf-8",
        make_dirs: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ) -> None:
        """Write content to a file on the remote system."""
        if isinstance(source, str | bytes):
            content = source
        else:
            content = source.read()
        if isinstance(content, str):
            content = content.encode(encoding)

        cmd = ["push", path]
        if make_dirs:
            cmd.append("-p")
        if permissions is not None:
            cmd.extend(["-m", oct(permissions)])
        if user:
            cmd.extend(["--user", user])
        elif user_id is not None:
            cmd.extend(["--uid", str(user_id)])
        if group:
            cmd.extend(["--group", group])
        elif group_id is not None:
            cmd.extend(["--gid", str(group_id)])

        if hasattr(self._runner, "upload_temp"):
            runner = cast(FileTransferRunner, self._runner)
            tmp_path = runner.upload_temp(content)
            try:
                cmd.insert(1, tmp_path)
                try:
                    self._run_command(cmd)
                except APIError as e:
                    self._raise_path_error(e)
            finally:
                runner.cleanup_temp(tmp_path)
        else:
            with tempfile.NamedTemporaryFile() as tmp_file:
                tmp_file.write(content)
                tmp_file.flush()
                cmd.insert(1, tmp_file.name)
                try:
                    self._run_command(cmd)
                except APIError as e:
                    self._raise_path_error(e)

    # Exec I/O is str if encoding is provided (the default)
    @overload
    def exec(
        self,
        command: list[str],
        *,
        service_context: str | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str | None = None,
        timeout: float | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
        stdin: str | TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        encoding: str = "utf-8",
        combine_stderr: bool = False,
    ) -> ExecProcess[str]: ...

    # Exec I/O is bytes if encoding is explicitly set to None
    @overload
    def exec(
        self,
        command: list[str],
        *,
        service_context: str | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str | None = None,
        timeout: float | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
        stdin: bytes | BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        stderr: BinaryIO | None = None,
        encoding: None = None,
        combine_stderr: bool = False,
    ) -> ExecProcess[bytes]: ...

    # Process execution
    def exec(
        self,
        command: list[str],
        *,
        service_context: str | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str | None = None,
        timeout: float | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
        stdin: str | bytes | TextIO | BinaryIO | None = None,
        stdout: TextIO | BinaryIO | None = None,
        stderr: TextIO | BinaryIO | None = None,
        encoding: str | None = "utf-8",
        combine_stderr: bool = False,
    ) -> ExecProcess:
        """Execute a command on the remote system."""
        # Build pebble exec command
        cmd = ["exec"]

        if service_context:
            cmd.extend(["--context", service_context])
        if working_dir:
            cmd.extend(["-w", working_dir])
        if timeout:
            cmd.extend(["--timeout", f"{timeout}s"])
        if user:
            cmd.extend(["--user", user])
        elif user_id is not None:
            cmd.extend(["--uid", str(user_id)])
        if group:
            cmd.extend(["--group", group])
        elif group_id is not None:
            cmd.extend(["--gid", str(group_id)])

        # Add environment variables
        if environment:
            for key, value in environment.items():
                cmd.extend(["--env", f"{key}={value}"])

        # Add the actual command
        cmd.append("--")
        cmd.extend(command)

        # Prepare stdin content
        stdin_content = None
        if stdin is not None:
            if isinstance(stdin, str | bytes):
                stdin_content = stdin
            else:
                stdin_content = stdin.read()

            if isinstance(stdin_content, str) and encoding is None:
                stdin_content = stdin_content.encode()
            elif isinstance(stdin_content, bytes) and encoding:
                stdin_content = stdin_content.decode(encoding)
            assert isinstance(stdin_content, (str | bytes))

        # Start the process
        full_cmd = [self.pebble_binary] + cmd

        # Determine stdio handling
        process_stdin = (
            subprocess.PIPE if stdin_content is not None or stdin is None else None
        )
        process_stdout = subprocess.PIPE if stdout is None else stdout
        process_stderr = (
            subprocess.PIPE if stderr is None and not combine_stderr else stderr
        )

        if combine_stderr and stderr is None:
            process_stderr = subprocess.STDOUT

        try:
            process = self._runner.popen(
                full_cmd,
                stdin=process_stdin,
                stdout=process_stdout,
                stderr=process_stderr,
                text=(encoding is not None),
                env=self._env,
            )
        except FileNotFoundError as e:
            raise ConnectionError(
                f"Pebble binary not found: {self.pebble_binary}"
            ) from e

        return ExecProcess(
            command=command,
            process=process,
            stdin_content=stdin_content,
            encoding=encoding,
            combine_stderr=combine_stderr,
            timeout=timeout,
        )

    # Change management
    def get_change(self, change_id: ChangeID) -> Change:
        # ``pebble tasks <id>`` returns the full change object (kind, tasks,
        # error and timing included), so we get the complete change directly
        # rather than scanning the whole list. A missing change surfaces as
        # ``error: cannot find change with id "<id>"``, which _run_command
        # already turns into a 404 APIError whose message matches the socket
        # client's, so no special-casing is needed here.
        data = self._run_json(["tasks", str(change_id)])
        return Change.from_dict(data)

    def abort_change(self, change_id: ChangeID) -> Change:
        """Unsupported: the Pebble CLI cannot abort a change.

        ops.pebble.Client.abort_change posts ``{"action": "abort"}`` to the
        changes API, but the CLI exposes no equivalent command (only ``pebble
        changes`` and ``pebble tasks`` exist under Changes), so there is no way
        to back this through the CLI. The method is provided so PebbleCliClient
        still satisfies PebbleClientProtocol / ops.pebble.Client's surface, and
        raises a clear error rather than ``AttributeError``.
        """
        raise NotImplementedError(
            "The Pebble CLI does not expose a command to abort a change, so "
            "shimmer cannot implement abort_change(). This is a limitation of "
            "the CLI, not of Pebble itself."
        )

    def get_changes(
        self,
        select: ChangeState = ChangeState.IN_PROGRESS,
        service: str | None = None,
    ) -> list[Change]:
        """Get list of changes.

        ``select`` defaults to ``ChangeState.IN_PROGRESS`` to match
        ops.pebble.Client (which returns only in-progress changes by default).
        """
        cmd = ["changes"]
        if service:
            cmd.append(service)

        data = self._run_json(cmd)
        if not data:
            return []
        changes = [Change.from_dict(change) for change in data["changes"]]
        # The CLI always returns every change; apply the ``select`` filter here
        # to match ops.pebble.Client semantics.
        if select == ChangeState.READY:
            changes = [c for c in changes if c.ready]
        elif select == ChangeState.IN_PROGRESS:
            changes = [c for c in changes if not c.ready]
        return changes

    def wait_change(
        self,
        change_id: ChangeID,
        timeout: float | None = 30.0,
        delay: float = 0.1,
    ) -> Change:
        """Wait for a change to be ready, polling until it completes.

        Mirrors ops.pebble.Client.wait_change: returns the ready change, or
        raises ops.pebble.TimeoutError if it is not ready within ``timeout``
        seconds (``timeout=None`` waits indefinitely).
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            change = self.get_change(change_id)
            if change.ready:
                return change
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"timed out waiting for change {change_id} ({timeout} seconds)"
                )
            time.sleep(delay)

    def get_notices(
        self,
        *,
        users: NoticesUsers | None = None,
        user_id: int | None = None,
        types: Iterable[NoticeType | str] | None = None,
        keys: Iterable[str] | None = None,
    ) -> list[Notice]:
        """Get notices."""
        cmd = ["notices"]
        if users:
            cmd.extend(["--users", str(users)])
        if user_id is not None:
            cmd.extend(["--uid", str(user_id)])
        for t in types or []:
            cmd.extend(["--type", t.value if isinstance(t, NoticeType) else t])
        for k in keys or []:
            cmd.extend(["--key", k])

        # ``--format json`` emits one object per notice with the full set of
        # fields in the Pebble API wire format, so each entry can be handed
        # straight to Notice.from_dict (no per-ID detail fetch needed).
        data = self._run_json(cmd)
        return [Notice.from_dict(notice) for notice in data["notices"]]

    def get_notice(self, id: str) -> Notice:
        """Get a specific notice by ID."""
        # ``pebble notice <id> --format json`` emits the notice in the Pebble
        # API wire format, so it can be handed straight to Notice.from_dict.
        data = self._run_json(["notice", id])
        return Notice.from_dict(data)

    def notify(
        self,
        type: NoticeType,
        key: str,
        *,
        data: dict[str, str] | None = None,
        repeat_after: datetime.timedelta | None = None,
    ) -> str:
        """Record a notice."""
        if type.value != "custom":
            raise ValueError("Only custom notices are supported")
        cmd = ["notify"]
        if repeat_after is not None:
            # Pebble expects a Go duration string (e.g. "1800s"), not bare seconds.
            cmd.extend(["--repeat-after", f"{repeat_after.total_seconds()}s"])
        cmd.append(key)
        for name, value in (data or {}).items():
            cmd.extend([f"{name}={value}"])

        result = self._run_command(cmd)
        # The output looks like: "Recorded notice 38"
        return result.stdout.strip().split()[-1]

    def get_warnings(
        self,
        select: WarningState = WarningState.PENDING,
    ) -> list[Warning]:
        """Get list of warnings in given state (pending or all).

        Under the hood, Pebble surfaces warnings as notices of type ``warning``.
        ``pebble warnings --format json`` (added in Pebble v1.31.0) emits the
        matching notices, which we map back to ``ops.pebble.Warning`` for
        drop-in compatibility with ``ops.pebble.Client``.
        """
        cmd = ["warnings"]
        if select == WarningState.ALL:
            cmd.append("--all")
        data = self._run_json(cmd)
        if not data:
            return []
        warnings: list[Warning] = []
        for notice in data.get("warnings", []):
            # The notice's ``key`` is the warning body; the ``occurred`` fields
            # map to the ops ``added`` fields. ``last-shown`` is a per-client
            # concept that Pebble tracks in local CLI state rather than on the
            # notice, so it's left unset.
            warnings.append(
                Warning.from_dict(
                    {
                        "message": notice["key"],
                        "first-added": notice["first-occurred"],
                        "last-added": notice["last-occurred"],
                        "expire-after": notice.get("expire-after", ""),
                        "repeat-after": notice.get("repeat-after", ""),
                    }
                )
            )
        return warnings

    def ack_warnings(self, timestamp: datetime.datetime) -> int:
        """Unsupported: ``pebble okay`` acks stateful, not by timestamp."""
        # The socket client POSTs {"action": "okay", "timestamp": ...} to
        # /v1/warnings; the CLI's ``pebble okay`` acks whatever the local CLI
        # state file marks as "last listed" and takes no timestamp argument, so
        # we can't reproduce the by-timestamp semantics ops.pebble.Client
        # promises. Rather than silently ack the wrong set, we surface this.
        raise NotImplementedError(
            "ack_warnings() cannot be implemented via the pebble CLI: "
            "`pebble okay` acks by local CLI state, not by timestamp. "
            "Use the socket client if you need timestamp-based acking."
        )

    def get_identities(self) -> dict[str, Identity]:
        """Get all identities."""
        data = self._run_json(["identities"])
        if not data:
            return {}
        return {
            name: Identity.from_dict(identity)
            for name, identity in data["identities"].items()
        }

    def replace_identities(
        self,
        identities: Mapping[str, IdentityDict | Identity | None],
    ):
        """Replace identities."""
        identity_data = {}
        for name, identity in identities.items():
            if identity is None:
                identity_data[name] = None
            elif isinstance(identity, Identity):
                identity_data[name] = identity.to_dict()
            else:
                identity_data[name] = identity

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml") as f:
            yaml.safe_dump({"identities": identity_data}, f)
            f.flush()
            cmd = ["update-identities", "--from", f.name, "--replace"]
            self._run_command(cmd)

    def remove_identities(self, identities: Iterable[str]):
        """Remove identities."""
        identity_names = list(identities)
        removal_dict = dict.fromkeys(identity_names)
        self.replace_identities(removal_dict)
