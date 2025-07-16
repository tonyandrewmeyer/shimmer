"""Protocol that covers both the shimmer client and the ops.pebble.Client."""

from __future__ import annotations

import datetime
import urllib.request
from collections.abc import Iterable, Mapping
from typing import Any, BinaryIO, Protocol, TextIO, overload

import ops


class PebbleClientProtocol(Protocol):
    """Protocol for Pebble client operations."""

    def __init__(
        self,
        socket_path: str,
        opener: urllib.request.OpenerDirector | None = None,
        base_url: str = "http://localhost",
        timeout: float = 5.0,
    ): ...

    def get_system_info(self) -> ops.pebble.SystemInfo: ...

    def get_warnings(
        self, select: ops.pebble.WarningState = ops.pebble.WarningState.PENDING
    ) -> list[ops.pebble.Warning]: ...
    def ack_warnings(self, timestamp: datetime.datetime) -> int: ...

    def get_changes(
        self,
        select: ops.pebble.ChangeState = ops.pebble.ChangeState.IN_PROGRESS,
        service: str | None = None,
    ) -> list[ops.pebble.Change]: ...
    def get_change(self, change_id: ops.pebble.ChangeID) -> ops.pebble.Change: ...
    def abort_change(self, change_id: ops.pebble.ChangeID) -> ops.pebble.Change: ...

    def autostart_services(
        self, timeout: float = 30.0, delay: float = 0.1
    ) -> ops.pebble.ChangeID: ...
    def replan_services(
        self, timeout: float = 30.0, delay: float = 0.1
    ) -> ops.pebble.ChangeID: ...
    def start_services(
        self,
        services: Iterable[str],
        timeout: float = 30.0,
        delay: float = 0.1,
    ) -> ops.pebble.ChangeID: ...
    def stop_services(
        self,
        services: Iterable[str],
        timeout: float = 30.0,
        delay: float = 0.1,
    ) -> ops.pebble.ChangeID: ...
    def restart_services(
        self,
        services: Iterable[str],
        timeout: float = 30.0,
        delay: float = 0.1,
    ) -> ops.pebble.ChangeID: ...
    def wait_change(
        self,
        change_id: ops.pebble.ChangeID,
        timeout: float | None = 30.0,
        delay: float = 0.1,
    ) -> ops.pebble.Change: ...

    def add_layer(
        self,
        label: str,
        layer: str | ops.pebble.LayerDict | ops.pebble.Layer,
        *,
        combine: bool = False,
    ): ...
    def get_plan(self) -> ops.pebble.Plan: ...
    def get_services(
        self, names: Iterable[str] | None = None
    ) -> list[ops.pebble.ServiceInfo]: ...

    @overload
    def pull(self, path: str, *, encoding: None) -> BinaryIO: ...
    @overload
    def pull(self, path: str, *, encoding: str = "utf-8") -> TextIO: ...
    def pull(
        self, path: str, *, encoding: str | None = "utf-8"
    ) -> BinaryIO | TextIO: ...

    def push(
        self,
        path: str,
        source: ops.pebble._IOSource,  # type: ignore
        *,
        encoding: str = "utf-8",
        make_dirs: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ): ...
    def list_files(
        self, path: str, *, pattern: str | None = None, itself: bool = False
    ) -> list[ops.pebble.FileInfo]: ...
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
    ): ...
    def remove_path(self, path: str, *, recursive: bool = False): ...

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
    ) -> ops.pebble.ExecProcess[str]: ...
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
    ) -> ops.pebble.ExecProcess[bytes]: ...
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
    ) -> ops.pebble.ExecProcess[Any]: ...

    def send_signal(self, sig: int | str, services: Iterable[str]): ...

    def get_checks(
        self,
        level: ops.pebble.CheckLevel | None = None,
        names: Iterable[str] | None = None,
    ) -> list[ops.pebble.CheckInfo]: ...
    def start_checks(self, checks: Iterable[str]) -> list[str]: ...
    def stop_checks(self, checks: Iterable[str]) -> list[str]: ...

    def notify(
        self,
        type: ops.pebble.NoticeType,
        key: str,
        *,
        data: dict[str, str] | None = None,
        repeat_after: datetime.timedelta | None = None,
    ) -> str: ...
    def get_notice(self, id: str) -> ops.pebble.Notice: ...
    def get_notices(
        self,
        *,
        users: ops.pebble.NoticesUsers | None = None,
        user_id: int | None = None,
        types: Iterable[ops.pebble.NoticeType | str] | None = None,
        keys: Iterable[str] | None = None,
    ) -> list[ops.pebble.Notice]: ...

    def get_identities(self) -> dict[str, ops.pebble.Identity]: ...
    def replace_identities(
        self,
        identities: Mapping[str, ops.pebble.IdentityDict | ops.pebble.Identity | None],
    ): ...
    def remove_identities(self, identities: Iterable[str]): ...
