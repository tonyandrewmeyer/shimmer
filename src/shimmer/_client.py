"""Shimmer - shiny Pebble client

This module provides a PebbleCliClient class that implements the same interface as
ops.pebble.Client but communicates with Pebble via CLI commands instead of via a
socket.
"""

from __future__ import annotations

import datetime
import fnmatch
import io
import os
import pathlib
import signal
import subprocess
import tempfile
import time
from collections.abc import Iterable
from typing import Any, BinaryIO, TextIO

import yaml

# Import all the types and exceptions from ops.pebble for compatibility
from ops.pebble import (
    APIError,
    BasicIdentity,
    Change,
    ChangeID,
    ChangeState,
    CheckInfo,
    CheckLevel,
    ConnectionError,
    FileInfo,
    FileType,
    Identity,
    IdentityDict,
    Layer,
    LocalIdentity,
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
        filtered_names = set(names) if names else None
        cmd = ["services", "--abs-time"]
        result = self._run_command(cmd)
        if result.stdout.strip() == "Plan has no services.":
            return []
        # Output looks like:
        # Service      Startup  Current  Since
        # demo-server  enabled  active   2025-07-12T06:55:57Z
        lines = result.stdout.strip().splitlines()[1:]
        services: list[ServiceInfo] = []
        for line in lines:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            service, startup, current, _ = parts
            if filtered_names is not None and service not in filtered_names:
                continue
            services.append(ServiceInfo(name=service, startup=startup, current=current))
        return services

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

        result = self._run_command(cmd)

        checks = []
        lines = result.stdout.strip().split("\n")
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 3:
                check_name = parts[0]
                if names and check_name not in names:
                    continue
                checks.append(CheckInfo(check_name, parts[1], parts[2]))
        return checks

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
        cmd = ["ls", "--abs-time", "-l", path]
        if itself:
            cmd.append("-d")

        result = self._run_command(cmd)
        # Output looks like:
        # drwxr-xr-x  root  root       -  2025-07-12T06:43:11Z  dev

        files = []
        lines = result.stdout.strip().split("\n")
        for line in lines:
            if not line.strip():
                continue
            parts = line.split(None, 6)
            if len(parts) < 6:
                continue
            name = parts[-1]
            if pattern and not fnmatch.fnmatch(name, pattern):
                continue
            permissions = self._permissions_to_int(parts[0][1:])
            user = parts[1]
            user_id = 0 if user == "root" else os.getuid()
            group = parts[2]
            group_id = 0 if group == "root" else os.getgid()
            file_info = FileInfo(
                path=path,
                name=name,
                type=FileType.DIRECTORY if parts[0].startswith("d") else FileType.FILE,
                permissions=permissions,
                user=user,
                user_id=user_id,
                group=group,
                group_id=group_id,
                size=self._human_size_to_int(parts[3]),
                last_modified=datetime.datetime.fromisoformat(parts[4]),
            )
            files.append(file_info)
        return files

    @staticmethod
    def _human_size_to_int(size: str) -> int | None:
        """Convert human-readable size (e.g., '1K', '2M') to bytes."""
        if size == "-":
            return None
        size = size.strip().upper()
        if size.endswith("KB"):
            return int(size[:-2]) * 1024
        elif size.endswith("MB"):
            return int(size[:-2]) * 1024 * 1024
        elif size.endswith("GB"):
            return int(size[:-2]) * 1024 * 1024 * 1024
        elif size.endswith("B"):
            return int(size[:-1])
        else:
            raise ValueError(f"Invalid size format: {size}")

    @staticmethod
    def _permissions_to_int(perm_string: str, /):
        """Convert a permission string like 'rw-rw-r--' to an integer."""
        if len(perm_string) != 9:
            raise ValueError("Permission string must be exactly 9 characters")

        result = 0
        for i in range(0, 9, 3):
            group_value = 0
            if perm_string[i] == "r":
                group_value += 4
            if perm_string[i + 1] == "w":
                group_value += 2
            if perm_string[i + 2] == "x":
                group_value += 1
            result = (result << 3) | group_value
        return result

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
    def get_changes(
        self,
        select: ChangeState | None = None,
        service: str | None = None,
    ) -> list[Change]:
        """Get list of changes."""
        cmd = ["changes", "--abs-time"]
        if select:
            cmd.extend(["--select", str(select)])

        result = self._run_command(cmd)

        # Parse changes output.
        # Output looks like:
        # ID   Status  Spawn                 Ready                 Summary
        # 1    Error   2025-07-12T06:49:22Z  2025-07-12T06:50:52Z  Perform HTTP check "demo-health"
        changes: list[Change] = []
        lines = result.stdout.strip().splitlines()
        if not lines or len(lines) < 2 or lines[0].strip() == "No changes.":
            return changes

        header = lines[0]
        # Find column start indices by header.
        columns = ["ID", "Status", "Spawn", "Ready", "Summary"]
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
            if len(fields) == 5:
                change = Change(
                    id=fields[0],
                    kind="unknown",  # Kind is not available in CLI output
                    tasks=[],  # Tasks are not available in CLI output
                    ready=fields[0] in ("Done", "Error"),
                    err=None,  # Error is not available in CLI output
                    status=fields[1],
                    spawn_time=datetime.datetime.fromisoformat(fields[2]),
                    ready_time=None,
                    summary=fields[4],
                )
            changes.append(change)
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
        cmd = ["identities"]
        result = self._run_command(cmd)

        identities = {}
        lines = result.stdout.strip().split("\n")
        if lines == ["No identities."]:
            return identities

        for line in lines[1:]:  # Skip header
            if not line.strip():
                continue

            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                access = parts[1]
                types = parts[2].split(",")
                basic = BasicIdentity("*****") if "basic" in types else None
                local = LocalIdentity(user_id=-1) if "local" in types else None
                identities[name] = Identity(access, basic=basic, local=local)

        return identities

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
