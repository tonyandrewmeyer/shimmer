"""Runner protocol and default local-subprocess implementation.

A ``Runner`` is responsible for dispatching a ``pebble …`` argv to the
appropriate execution backend.  The default, ``LocalSubprocessRunner``,
reproduces the behaviour that was previously inline in ``PebbleCliClient``.
Remote runners (e.g. a ``JujuSshRunner`` that prefixes the argv with
``juju ssh --container=<c> <unit> --``) can implement the same two-method
protocol without touching ``PebbleCliClient`` at all.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import tempfile
from collections.abc import Mapping
from typing import IO, Any, Protocol, runtime_checkable


@runtime_checkable
class Runner(Protocol):
    """Protocol for command dispatch in ``PebbleCliClient``.

    Implementations must provide two methods that mirror ``subprocess.run``
    and ``subprocess.Popen`` for the argument shapes that ``PebbleCliClient``
    actually uses.

    **env handling**: the client passes ``self._env`` (a copy of
    ``os.environ`` possibly augmented with ``PEBBLE``/``PEBBLE_SOCKET``) as
    the ``env`` argument.  ``LocalSubprocessRunner`` forwards it unchanged to
    the subprocess, which is identical to the previous inline behaviour.
    Remote runners may need to translate these variables into the remote
    environment (e.g. as ``env KEY=VAL …`` prefixes on ``juju ssh``) or
    ignore them entirely when the remote binary has its own defaults.
    """

    def run(
        self,
        argv: list[str],
        *,
        input: str | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        """Run *argv* to completion and return the result.

        Implementations should capture stdout and stderr and use text mode,
        mirroring ``subprocess.run(..., capture_output=True, text=True)``.
        """
        ...

    def popen(
        self,
        argv: list[str],
        *,
        stdin: int | IO[Any] | None,
        stdout: int | IO[Any] | None,
        stderr: int | IO[Any] | None,
        text: bool,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.Popen[Any]:
        """Start *argv* as a background process and return the handle.

        Mirrors ``subprocess.Popen`` for the streaming ``exec`` path.
        """
        ...


@runtime_checkable
class FileTransferRunner(Runner, Protocol):
    """Optional extension of ``Runner`` for staging files to pebble's filesystem.

    Implement this on remote runners (e.g. ``JujuSshRunner``) so that
    ``PebbleCliClient.push`` and ``pull`` can stage content on the remote host
    rather than a local temp file that the remote pebble process cannot access.

    ``LocalSubprocessRunner`` implements this protocol — local and remote
    filesystems are the same, so the default behaviour is preserved.
    """

    def upload_temp(self, content: bytes) -> str:
        """Write *content* to a temp file accessible to pebble.

        Returns the absolute path that pebble can use as a source (push) or
        destination (pull).  Call ``cleanup_temp`` when the temp file is no
        longer needed.
        """
        ...

    def download_temp(self, path: str) -> bytes:
        """Return the bytes stored at *path* on pebble's filesystem."""
        ...

    def cleanup_temp(self, path: str) -> None:
        """Remove the temp file at *path* on pebble's filesystem.

        Called after ``upload_temp`` or ``download_temp`` to release the
        staging file.
        """
        ...


class LocalSubprocessRunner:
    """Default runner: executes commands as local subprocesses.

    This is a direct extraction of the behaviour that was previously inline
    in ``PebbleCliClient._run_command`` and ``PebbleCliClient.exec``.
    Existing callers see no behaviour change.
    """

    def run(
        self,
        argv: list[str],
        *,
        input: str | None = None,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[Any]:
        return subprocess.run(
            argv,
            input=input,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=check,
        )

    def popen(
        self,
        argv: list[str],
        *,
        stdin: int | IO[Any] | None,
        stdout: int | IO[Any] | None,
        stderr: int | IO[Any] | None,
        text: bool,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.Popen[Any]:
        return subprocess.Popen(
            argv,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            text=text,
            env=env,
        )

    def upload_temp(self, content: bytes) -> str:
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
        except BaseException:
            pathlib.Path(path).unlink(missing_ok=True)
            raise
        return path

    def download_temp(self, path: str) -> bytes:
        with open(path, "rb") as fh:
            return fh.read()

    def cleanup_temp(self, path: str) -> None:
        pathlib.Path(path).unlink(missing_ok=True)
