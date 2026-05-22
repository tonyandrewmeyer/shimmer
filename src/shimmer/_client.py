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
from collections.abc import Iterable
from typing import Any, BinaryIO, TextIO, overload

import yaml

# Import all the types and exceptions from ops.pebble for compatibility
from ops.pebble import (
    APIError,
    Change,
    ChangeID,
    ChangeState,
    CheckInfo,
    CheckLevel,
    ConnectionError,
    FileInfo,
    Identity,
    IdentityDict,
    Layer,
    Notice,
    NoticesUsers,
    NoticeType,
    Plan,
    ServiceInfo,
    SystemInfo,
    TimeoutError,
    Warning,
    WarningState,
)

from ._process import ExecProcess


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
    ):
        self.timeout = timeout
        self.pebble_binary = pebble_binary
        self._env = os.environ.copy()
        if socket_path:
            self._env["PEBBLE"] = str(pathlib.Path(socket_path).parent)

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
            result = subprocess.run(
                full_cmd,
                input=input_data,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                env=self._env,
                check=check,
            )
            return result
        except subprocess.CalledProcessError as e:
            raise APIError(
                body={"message": e.stderr or str(e)},
                code=e.returncode,
                status="Command Failed",
                message=e.stderr or str(e),
            ) from e
        except subprocess.TimeoutExpired as e:
            raise TimeoutError(f"Command {full_cmd} timed out") from e
        except FileNotFoundError as e:
            raise ConnectionError(
                f"Pebble binary not found: {self.pebble_binary}"
            ) from e

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
        result = self._run_command(["version", "--client"])
        lines = result.stdout.strip().split("\n")
        return SystemInfo(lines[0].strip())

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

    def replan_services(
        self,
        *,
        timeout: float = 30.0,
        delay: float | None = None,
    ) -> ChangeID:
        """Replan services."""
        if delay is not None:
            time.sleep(delay)

        cmd = ["replan"]
        if timeout == 0:
            cmd.append("--no-wait")

        result = self._run_command(cmd)
        # We only get the change ID if using --no-wait.
        if timeout == 0:
            return ChangeID(result.stdout.strip())
        return ChangeID("?")

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

        cmd = ["start"] + service_list
        if timeout == 0:
            cmd.append("--no-wait")

        result = self._run_command(cmd)
        # We only get the change ID if using --no-wait.
        if timeout == 0:
            return ChangeID(result.stdout.strip())
        return ChangeID("?")

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

        cmd = ["stop"] + service_list
        if timeout == 0:
            cmd.append("--no-wait")

        result = self._run_command(cmd)
        # We only get the change ID if using --no-wait.
        if timeout == 0:
            return ChangeID(result.stdout.strip())
        return ChangeID("?")

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

        cmd = ["restart"] + service_list
        if timeout == 0:
            cmd.append("--no-wait")

        result = self._run_command(cmd)
        # We only get the change ID if using --no-wait.
        if timeout == 0:
            return ChangeID(result.stdout.strip())
        return ChangeID("?")

    def autostart_services(
        self,
        *,
        timeout: float = 30.0,
        delay: float | None = None,
    ) -> ChangeID:
        """Start all startup-enabled services."""
        # There's no direct CLI equivalent, use replan which starts enabled services.
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
            if not hasattr(signal, sig):
                raise ValueError(f"Invalid signal name: {sig}")
            sig_name = sig
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

    def start_checks(self, checks: Iterable[str]) -> list[str]:
        """Start checks."""
        check_list = list(checks)
        if not check_list:
            raise ValueError("checks list cannot be empty")

        cmd = ["start-checks"] + check_list
        self._run_command(cmd)

        # Return list of started checks (assume all were started)
        return check_list

    def stop_checks(self, checks: Iterable[str]) -> list[str]:
        """Stop checks."""
        check_list = list(checks)
        if not check_list:
            raise ValueError("checks list cannot be empty")

        cmd = ["stop-checks"] + check_list
        self._run_command(cmd)

        # Return list of stopped checks (assume all were stopped)
        return check_list

    # File operations
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

        data = self._run_json(cmd)
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

        self._run_command(cmd)

    def remove_path(self, path: str, *, recursive: bool = False) -> None:
        """Remove a file or directory."""
        cmd = ["rm", path]
        if recursive:
            cmd.append("--recursive")

        self._run_command(cmd)

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
        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.close()
            cmd = ["pull", path, tmp_file.name]
            self._run_command(cmd)
            if encoding is None:
                with open(tmp_file.name, "rb") as tmp_file:
                    return io.BytesIO(tmp_file.read())
            with open(tmp_file.name, encoding=encoding) as tmp_file:
                return io.StringIO(tmp_file.read())

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
        if hasattr(source, "read") and callable(source.read):
            content = source.read()
        else:
            content = source
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

        with tempfile.NamedTemporaryFile() as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            cmd.insert(1, tmp_file.name)
            self._run_command(cmd)

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
            if hasattr(stdin, "read") and callable(stdin.read):
                stdin_content = stdin.read()
            else:
                stdin_content = stdin

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
            process = subprocess.Popen(
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
            stdin_content=stdin_content,  # type: ignore
            encoding=encoding,
            combine_stderr=combine_stderr,
            timeout=timeout,
        )

    # Change management
    def get_change(self, change_id: ChangeID) -> Change:
        # ``pebble tasks <id>`` returns the full change object (kind, tasks,
        # error and timing included), so we get the complete change directly
        # rather than scanning the whole list.
        try:
            data = self._run_json(["tasks", str(change_id)])
        except APIError as e:
            message = f"Could not find change {change_id}"
            raise APIError(
                body={"message": message},
                code=404,
                status="Command Failed",
                message=message,
            ) from e
        return Change.from_dict(data)

    def get_changes(
        self,
        select: ChangeState | None = None,
        service: str | None = None,
    ) -> list[Change]:
        """Get list of changes."""
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
        *,
        timeout: float | None = None,
        delay: float = 0.1,
    ) -> Change:
        """Wait for a change to be ready."""
        raise NotImplementedError

    def get_notices(
        self,
        *,
        users: NoticesUsers | None = None,
        user_id: int | None = None,
        types: Iterable[NoticeType | str] | None = None,
        keys: Iterable[str] | None = None,
    ) -> list[Notice]:
        """Get notices."""
        cmd = ["notices", "--abs-time"]
        if users:
            cmd.extend(["--users", str(users)])
        if user_id is not None:
            cmd.extend(["--uid", str(user_id)])
        for t in types or []:
            if isinstance(t, NoticeType):
                cmd.append(str(t))
            else:
                cmd.append(t)
        for k in keys or []:
            cmd.extend(["--key", k])

        result = self._run_command(cmd)
        # Output looks like:
        # ID   User    Type           Key                    First               Repeated            Occurrences
        # 2    public  change-update  2                      today at 06:49 UTC  today at 06:49 UTC  3
        notices: list[Notice] = []
        lines = result.stdout.strip().splitlines()
        if not lines or len(lines) < 2:
            return notices

        header = lines[0]
        # Find column start indices by header.
        columns = ["ID", "User", "Type", "Key", "First", "Repeated", "Occurrences"]
        col_starts: list[int | None] = []
        for col in columns:
            idx = header.find(col)
            if idx == -1:
                raise ValueError(f"Column '{col}' not found in header: {header}")
            col_starts.append(idx)
        # Add end index for easier slicing.
        col_starts.append(None)

        for line in lines[1:]:
            if not line.strip():
                continue
            fields: list[str] = []
            for i in range(len(columns)):
                start = col_starts[i]
                end = col_starts[i + 1]
                value = (
                    line[start:end].strip() if end is not None else line[start:].strip()
                )
                fields.append(value)
            if len(fields) == 7:
                notice = Notice(
                    id=fields[0],
                    user_id=None if fields[1] == "public" else int(fields[1]),
                    type=fields[2],
                    key=fields[3],
                    first_occurred=fields[4],
                    last_repeated=fields[5],
                    last_occurred=datetime.datetime.now(),  # Not available in CLI output
                    occurrences=int(fields[6]),
                )
            notices.append(notice)
        return notices

    def get_notice(self, id: str) -> Notice:
        """Get a specific notice by ID."""
        cmd = ["notice", id]
        self._run_command(cmd)
        # Output looks like:
        # Recorded notice 12
        return self.get_notices(keys=[id])[0]

    def notify(
        self,
        type: NoticeType,
        key: str,
        *,
        data: dict[str, str] | None = None,
        repeat_after: datetime.timedelta | None = None,
    ) -> str:
        """Record a notice."""
        assert type.value == "custom", "Only custom notices are supported"
        cmd = ["notify"]
        if repeat_after:
            cmd.extend(["--repeat-after", str(repeat_after.total_seconds())])
        cmd.append(key)
        for name, value in (data or {}).items():
            cmd.extend([f"{name}={value}"])

        result = self._run_command(cmd)
        # The output looks like: "Recorded notice 38"
        return result.stdout.strip().split()[-1]

    def get_warnings(
        self,
        select: WarningState | None = None,
    ) -> list[Warning]:
        """Get warnings."""
        cmd = ["warnings"]
        if select:
            cmd.extend(["--select", str(select)])

        result = self._run_command(cmd)
        warnings: list[Warning] = []
        if result == "No warnings.":
            return warnings

        raise NotImplementedError

    def ack_warnings(self, timestamp: datetime.datetime) -> int:
        """Acknowledge warnings up to timestamp."""
        raise NotImplementedError

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
        identities: dict[str, IdentityDict | Identity | None],
    ):
        """Replace identities."""
        identity_data = {}
        for name, identity in identities.items():
            if identity is None:
                identity_data[name] = None
            elif hasattr(identity, "to_dict"):
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
