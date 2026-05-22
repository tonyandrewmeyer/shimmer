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

__all__ = [
    "PebbleCliClient",
    "ExecProcess",
    "PebbleClientProtocol",
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
