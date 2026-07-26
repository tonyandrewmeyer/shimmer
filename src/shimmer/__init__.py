"""Shimmer - A drop-in replacement for ops.pebble.Client."""

from importlib.metadata import PackageNotFoundError, version

# Re-export the pebble exception hierarchy so callers can catch shimmer errors
# without also importing ops.pebble (shimmer raises these same types).
from ops.pebble import (
    APIError,
    ChangeError,
    ConnectionError,
    Error,
    ExecError,
    PathError,
    ProtocolError,
    TimeoutError,
)

from ._client import PebbleCliClient
from ._process import ExecProcess
from ._protocol import PebbleClientProtocol
from ._runner import FileTransferRunner, LocalSubprocessRunner, Runner

# Grouped by origin rather than sorted: shimmer's own API first, then the
# ops.pebble exceptions re-exported for drop-in compatibility (with the base
# ``Error`` leading its group).
__all__ = [  # noqa: RUF022
    "PebbleCliClient",
    "ExecProcess",
    "FileTransferRunner",
    "LocalSubprocessRunner",
    "PebbleClientProtocol",
    "Runner",
    # Re-exported ops.pebble exceptions.
    "Error",
    "APIError",
    "ChangeError",
    "ConnectionError",
    "ExecError",
    "PathError",
    "ProtocolError",
    "TimeoutError",
]

try:
    __version__ = version("pebble-shimmer")
except PackageNotFoundError:  # pragma: no cover - running from an uninstalled tree
    __version__ = "0.0.0+unknown"
