"""Shimmer - A drop-in replacement for ops.pebble.Client."""

from importlib.metadata import PackageNotFoundError, version

from ._client import PebbleCliClient
from ._process import ExecProcess
from ._protocol import PebbleClientProtocol

__all__ = ["PebbleCliClient", "ExecProcess", "PebbleClientProtocol"]

try:
    __version__ = version("pebble-shimmer")
except PackageNotFoundError:  # pragma: no cover - running from an uninstalled tree
    __version__ = "0.0.0+unknown"
