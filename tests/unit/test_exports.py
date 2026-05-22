"""Shimmer re-exports the ops.pebble exception hierarchy from its top level."""

import ops.pebble

import shimmer

EXCEPTIONS = [
    "Error",
    "APIError",
    "ChangeError",
    "ConnectionError",
    "ExecError",
    "PathError",
    "ProtocolError",
    "TimeoutError",
]


def test_exceptions_are_reexported_from_ops_pebble():
    for name in EXCEPTIONS:
        assert getattr(shimmer, name) is getattr(ops.pebble, name)


def test_exceptions_are_listed_in_all():
    for name in EXCEPTIONS:
        assert name in shimmer.__all__
