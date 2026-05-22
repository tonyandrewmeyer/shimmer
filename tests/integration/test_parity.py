#! /usr/bin/env python

"""Parity tests: shimmer (CLI) must behave exactly like ops.pebble.Client.

Each test applies the same operation to two identical Pebble daemons -- one
driven by :class:`ops.pebble.Client` over its socket, one by
:class:`shimmer.PebbleCliClient` via the CLI -- and asserts the observable
results match. See :mod:`conftest` for the twin-daemon fixture and the
normalisation/comparison helpers.

Where a test is marked ``xfail`` it documents a real, known divergence between
shimmer and ops.pebble.Client (not a flaky test); see the reason string.
"""

from __future__ import annotations

import signal
import time

import ops
import pytest

from .conftest import (
    Twins,
    assert_parity,
    assert_same_exception,
    assert_same_outcome,
    both_results,
    wait_until_ready,
)

pytestmark = pytest.mark.integration


# A second layer used by mutation tests, identical for both daemons.
EXTRA_LAYER = """\
summary: Dynamic test layer
services:
  dynamic-service:
    override: replace
    command: echo "dynamic service"
    startup: disabled
"""


class TestSystemParity:
    def test_get_system_info(self, twins: Twins):
        s, c = both_results(twins, lambda cl: cl.get_system_info())
        assert_parity(s, c)


class TestLayerParity:
    def test_get_plan(self, twins: Twins):
        s, c = both_results(twins, lambda cl: cl.get_plan())
        assert_parity(s, c)

    def test_add_layer(self, twins: Twins):
        for client in twins.both:
            client.add_layer("dynamic", EXTRA_LAYER)
        s, c = both_results(twins, lambda cl: cl.get_plan())
        assert_parity(s, c)
        assert "dynamic-service" in c.services

    def test_add_layer_combine(self, twins: Twins):
        override = """\
summary: override
services:
  test-service:
    override: merge
    environment:
      ADDED: "1"
"""
        for client in twins.both:
            client.add_layer("test", override, combine=True)
        s, c = both_results(twins, lambda cl: cl.get_plan())
        assert_parity(s, c)


class TestServiceParity:
    def test_get_services(self, twins: Twins):
        s, c = both_results(twins, lambda cl: cl.get_services())
        assert_parity(s, c)

    def test_get_services_named(self, twins: Twins):
        s, c = both_results(twins, lambda cl: cl.get_services(["test-service"]))
        assert_parity(s, c)

    def test_start_services(self, twins: Twins):
        # The change id is non-deterministic in form but both must return a str.
        for client in twins.both:
            change_id = client.start_services(["test-service"])
            assert isinstance(change_id, str) and change_id
        s, c = both_results(twins, lambda cl: cl.get_services(["test-service"]))
        assert_parity(s, c)
        assert c[0].current == ops.pebble.ServiceStatus.ACTIVE

    def test_stop_services(self, twins: Twins):
        for client in twins.both:
            client.start_services(["test-service"])
        for client in twins.both:
            client.stop_services(["test-service"])
        s, c = both_results(twins, lambda cl: cl.get_services(["test-service"]))
        assert_parity(s, c)
        assert c[0].current == ops.pebble.ServiceStatus.INACTIVE

    def test_restart_services(self, twins: Twins):
        for client in twins.both:
            client.start_services(["test-service"])
        for client in twins.both:
            client.restart_services(["test-service"])
        s, c = both_results(twins, lambda cl: cl.get_services(["test-service"]))
        assert_parity(s, c)
        assert c[0].current == ops.pebble.ServiceStatus.ACTIVE

    def test_start_returns_matching_change_id(self, twins_no_checks: Twins):
        # In no-wait mode (timeout=0) shimmer can parse the real change id from
        # the CLI, so it matches the socket client's id on lockstep daemons.
        s = twins_no_checks.socket.start_services(["test-service"], timeout=0)
        c = twins_no_checks.cli.start_services(["test-service"], timeout=0)
        assert str(s) == str(c)

    def test_start_returns_real_change_id_when_waiting(self, twins_no_checks: Twins):
        # Default (waiting) mode must still return the real change id.
        s = twins_no_checks.socket.start_services(["test-service"])
        c = twins_no_checks.cli.start_services(["test-service"])
        assert str(s) == str(c) != "?"

    def test_autostart_no_default_services(self, twins: Twins):
        # test-service is startup: disabled, so there is nothing to autostart;
        # both clients must raise APIError("no default services").
        assert_same_outcome(twins, lambda cl: cl.autostart_services(timeout=0))

    def test_send_signal(self, twins: Twins):
        for client in twins.both:
            client.start_services(["test-service"])
        time.sleep(0.5)
        for client in twins.both:
            # SIGCONT is a no-op for a running `sleep`, so the service stays up
            # on both sides and we compare the resulting (unchanged) state.
            client.send_signal(signal.SIGCONT, ["test-service"])
        s, c = both_results(twins, lambda cl: cl.get_services(["test-service"]))
        assert_parity(s, c)


class TestCheckParity:
    def test_get_checks(self, twins: Twins):
        s, c = both_results(twins, lambda cl: cl.get_checks())
        assert_parity(s, c)

    def test_get_checks_named(self, twins: Twins):
        s, c = both_results(twins, lambda cl: cl.get_checks(names=["test-check"]))
        assert_parity(s, c)

    def test_start_checks_readback(self, twins: Twins):
        # The resulting check state must match, regardless of the return value.
        for client in twins.both:
            client.start_checks(["test-check"])
        s, c = both_results(twins, lambda cl: cl.get_checks(names=["test-check"]))
        assert_parity(s, c)

    def test_stop_checks_readback(self, twins: Twins):
        for client in twins.both:
            client.stop_checks(["test-check"])
        s, c = both_results(twins, lambda cl: cl.get_checks(names=["test-check"]))
        assert_parity(s, c)

    def test_start_checks_return_value(self, twins: Twins):
        # test-check is already running, so nothing changes -> both return [].
        s, c = both_results(twins, lambda cl: cl.start_checks(["test-check"]))
        assert s == c


class TestFileParity:
    def test_push_pull_text(self, twins: Twins):
        content = "Hello from parity test!\n"
        for client in twins.both:
            client.push("/tmp/parity_text.txt", content)
        s, c = both_results(twins, lambda cl: cl.pull("/tmp/parity_text.txt").read())
        assert s == c == content

    def test_push_pull_binary(self, twins: Twins):
        content = b"\x00\x01\x02\x03\xff\xfe\xfd"
        for client in twins.both:
            client.push("/tmp/parity_bin", content)
        s, c = both_results(
            twins, lambda cl: cl.pull("/tmp/parity_bin", encoding=None).read()
        )
        assert s == c == content

    def test_list_files(self, twins: Twins):
        for client in twins.both:
            client.push("/tmp/parity_ls/a.txt", "a", make_dirs=True)
            client.push("/tmp/parity_ls/b.txt", "b", make_dirs=True)
        # last_modified is volatile and dropped by normalize().
        s, c = both_results(twins, lambda cl: cl.list_files("/tmp/parity_ls"))
        assert_parity(s, c)

    def test_list_files_pattern(self, twins: Twins):
        for client in twins.both:
            client.push("/tmp/parity_glob/keep.log", "x", make_dirs=True)
            client.push("/tmp/parity_glob/skip.txt", "y", make_dirs=True)
        s, c = both_results(
            twins, lambda cl: cl.list_files("/tmp/parity_glob", pattern="*.log")
        )
        assert_parity(s, c)

    def test_make_dir(self, twins: Twins):
        for client in twins.both:
            client.make_dir("/tmp/parity_mkdir/sub", make_parents=True)
        s, c = both_results(
            twins, lambda cl: cl.list_files("/tmp/parity_mkdir", itself=True)
        )
        assert_parity(s, c)

    def test_remove_path(self, twins: Twins):
        for client in twins.both:
            client.push("/tmp/parity_rm.txt", "bye")
            client.remove_path("/tmp/parity_rm.txt")
        s, c = both_results(twins, lambda cl: cl.list_files("/tmp"))
        # Both should agree the file is gone; comparing /tmp listings is heavy,
        # so just assert neither lists it.
        assert "parity_rm.txt" not in {f.name for f in c}
        assert "parity_rm.txt" not in {f.name for f in s}


class TestExecParity:
    def test_exec_simple(self, twins: Twins):
        s, c = both_results(
            twins, lambda cl: cl.exec(["echo", "hello world"]).wait_output()
        )
        assert s == c

    def test_exec_environment(self, twins: Twins):
        op = lambda cl: cl.exec(  # noqa: E731
            ["sh", "-c", 'echo "$TEST_VAR"'],
            environment={"TEST_VAR": "value"},
        ).wait_output()
        s, c = both_results(twins, op)
        assert s == c

    def test_exec_working_dir(self, twins: Twins):
        s, c = both_results(
            twins, lambda cl: cl.exec(["pwd"], working_dir="/tmp").wait_output()
        )
        assert s == c

    def test_exec_stdin(self, twins: Twins):
        s, c = both_results(
            twins, lambda cl: cl.exec(["cat"], stdin="piped\n").wait_output()
        )
        assert s == c

    def test_exec_failure(self, twins: Twins):
        op = lambda cl: cl.exec(["false"]).wait_output()  # noqa: E731
        socket_exc, cli_exc = assert_same_exception(twins, op)
        assert isinstance(socket_exc, ops.pebble.ExecError)
        assert isinstance(cli_exc, ops.pebble.ExecError)
        assert socket_exc.exit_code == cli_exc.exit_code
        assert socket_exc.command == cli_exc.command


class TestChangeParity:
    # These use the check-free fixture so the only change is the one we drive;
    # the BASE_LAYER check would otherwise spawn recurring perform-check changes
    # at different moments on each daemon. timeout=0 gives shimmer the real
    # change id (see TestServiceParity).

    def test_get_changes_ready(self, twins_no_checks: Twins):
        # Equalise the filter explicitly: with the change complete, select=READY
        # returns the single start change on both sides.
        for client in twins_no_checks.both:
            change_id = client.start_services(["test-service"], timeout=0)
            wait_until_ready(client, change_id)
        s, c = both_results(
            twins_no_checks,
            lambda cl: cl.get_changes(select=ops.pebble.ChangeState.READY),
        )
        assert_parity(s, c)

    def test_get_changes_default_select(self, twins_no_checks: Twins):
        for client in twins_no_checks.both:
            change_id = client.start_services(["test-service"], timeout=0)
            wait_until_ready(client, change_id)
        # Default select=IN_PROGRESS, so a completed change yields [] on both.
        s, c = both_results(twins_no_checks, lambda cl: cl.get_changes())
        assert_parity(s, c)

    def test_wait_change(self, twins_no_checks: Twins):
        socket_id = twins_no_checks.socket.start_services(["test-service"], timeout=0)
        cli_id = twins_no_checks.cli.start_services(["test-service"], timeout=0)
        s = twins_no_checks.socket.wait_change(socket_id, timeout=10.0)
        c = twins_no_checks.cli.wait_change(cli_id, timeout=10.0)
        assert s.ready and c.ready
        assert_parity(s, c)

    def test_get_change_by_id(self, twins_no_checks: Twins):
        socket_id = twins_no_checks.socket.start_services(["test-service"], timeout=0)
        cli_id = twins_no_checks.cli.start_services(["test-service"], timeout=0)
        wait_until_ready(twins_no_checks.socket, socket_id)
        wait_until_ready(twins_no_checks.cli, cli_id)
        s = twins_no_checks.socket.get_change(socket_id)
        c = twins_no_checks.cli.get_change(cli_id)
        assert_parity(s, c)


class TestNoticeParity:
    def test_notify_and_get_notices(self, twins: Twins):
        for client in twins.both:
            client.notify(
                ops.pebble.NoticeType.CUSTOM,
                "shimmer.test/parity",
                data={"hello": "world"},
            )
        s, c = both_results(twins, lambda cl: cl.get_notices())
        assert_parity(s, c)

    def test_get_notice_by_id(self, twins: Twins):
        socket_id = twins.socket.notify(
            ops.pebble.NoticeType.CUSTOM, "shimmer.test/byid", data={"k": "v"}
        )
        cli_id = twins.cli.notify(
            ops.pebble.NoticeType.CUSTOM, "shimmer.test/byid", data={"k": "v"}
        )
        s = twins.socket.get_notice(socket_id)
        c = twins.cli.get_notice(cli_id)
        assert_parity(s, c, drop={"id"})


# Warnings have no parity tests: they are deprecated in Pebble (the API
# endpoint is removed) and shimmer intentionally raises NotImplementedError for
# get_warnings()/ack_warnings(). That documented behaviour is covered by a
# unit test (tests/unit/test_client.py::...::test_warnings_unsupported).


class TestIdentityParity:
    # Use 'local' (user-id) identities: 'basic' auth stores a salted password
    # hash that differs between daemons, which is not a real divergence.
    IDENTITIES: dict[str, ops.pebble.IdentityDict] = {
        "alice": {"access": "admin", "local": {"user-id": 1000}}
    }

    def test_get_identities_empty(self, twins: Twins):
        s, c = both_results(twins, lambda cl: cl.get_identities())
        assert_parity(s, c)

    def test_replace_identities(self, twins: Twins):
        for client in twins.both:
            client.replace_identities(self.IDENTITIES)
        s, c = both_results(twins, lambda cl: cl.get_identities())
        assert_parity(s, c)
        assert "alice" in c

    def test_remove_identities(self, twins: Twins):
        for client in twins.both:
            client.replace_identities(self.IDENTITIES)
            client.remove_identities(["alice"])
        s, c = both_results(twins, lambda cl: cl.get_identities())
        assert_parity(s, c)
        assert "alice" not in c


class TestErrorParity:
    def test_start_unknown_service(self, twins: Twins):
        assert_same_exception(twins, lambda cl: cl.start_services(["nonexistent"]))

    def test_pull_missing_file(self, twins: Twins):
        # Both must raise ops.pebble.PathError (not APIError).
        socket_exc, _ = assert_same_exception(
            twins, lambda cl: cl.pull("/nonexistent/file.txt")
        )
        assert isinstance(socket_exc, ops.pebble.PathError)

    def test_remove_missing_file(self, twins: Twins):
        socket_exc, _ = assert_same_exception(
            twins, lambda cl: cl.remove_path("/nonexistent/file.txt")
        )
        assert isinstance(socket_exc, ops.pebble.PathError)

    def test_get_change_unknown_id(self, twins: Twins):
        assert_same_exception(twins, lambda cl: cl.get_change("999999"))
