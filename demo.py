#!/usr/bin/env python

"""Demo for Shimmer: prove PebbleCliClient is a drop-in for ops.pebble.Client.

The whole point of Shimmer is parity: the same code that drives the real
``ops.pebble.Client`` (over the unix socket) should drive ``PebbleCliClient``
(over the ``pebble`` CLI) with byte-identical results. This script makes that
claim concrete and shows the CLI commands Shimmer runs underneath.

Modes:
    uv run python demo.py                 build the Showboat document (demo.md)
    uv run python demo.py --record        record the tmux side-by-side (demo.cast)
    uv run python demo.py --client socket  run the workload via ops.pebble.Client
    uv run python demo.py --client cli      run the workload via PebbleCliClient

The last two are the entry points the tmux panes call; they are also handy on
their own. A running Pebble daemon is required (PEBBLE points at its home).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import ops.pebble

from shimmer import PebbleCliClient

DEMO_FILE = "demo.md"
CAST_FILE = "demo.cast"
RESULTS_DIR = "/tmp/shimmer-parity"
HTTP_URL = "http://localhost:8080"

# Pacing for the live recording; 0 keeps the Showboat build fast.
PACE = float(os.environ.get("DEMO_PACE", "0"))

# The workload deploys this layer. http.server gives us a real process we can
# curl, and the check proves Shimmer round-trips structured plan data.
LAYER = """\
summary: Demo web server
services:
  demo-server:
    override: replace
    summary: Demo HTTP server
    command: python3 -m http.server 8080
    startup: enabled
checks:
  demo-health:
    override: replace
    level: alive
    http:
      url: http://localhost:8080
    period: 30s
    timeout: 3s
"""


# --------------------------------------------------------------------------- #
# Clients
# --------------------------------------------------------------------------- #
def _socket_path() -> str:
    pebble = os.environ.get("PEBBLE", os.path.expanduser("~/pebble-demo"))
    return str(Path(pebble) / ".pebble.socket")


def socket_client() -> ops.pebble.Client:
    """The real ops client, talking to the daemon over its unix socket."""
    return ops.pebble.Client(socket_path=_socket_path())


class TracingCliClient(PebbleCliClient):
    """A PebbleCliClient that prints each underlying ``pebble`` command.

    This is only for the demo: it reveals what Shimmer shells out so the
    "over the CLI" story is visible rather than implied. Consecutive identical
    commands (e.g. the change-polling loop) are collapsed to one line, and
    run-to-run noise (temp paths, change IDs) is normalised so the document
    stays reproducible under ``showboat verify``.
    """

    _TMP_RE = re.compile(r"/tmp/tmp[A-Za-z0-9_]+")
    _ID_RE = re.compile(r"\b(tasks|change|wait) \d+")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._last_trace: str | None = None

    def _trace(self, parts: list[str]) -> None:
        line = " ".join(parts)
        line = self._TMP_RE.sub("/tmp/<tmp>", line)
        line = self._ID_RE.sub(r"\1 <id>", line)
        if line == self._last_trace:
            return
        self._last_trace = line
        sys.stdout.write(f"    \033[2m$ {self.pebble_binary} {line}\033[0m\n")
        sys.stdout.flush()

    def _run_command(self, cmd, *args, **kwargs):  # type: ignore[override]
        self._trace(list(cmd))
        return super()._run_command(cmd, *args, **kwargs)

    def exec(self, command, **kwargs):  # type: ignore[override]
        parts = ["exec"]
        for key, value in (kwargs.get("environment") or {}).items():
            parts += ["--env", f"{key}={value}"]
        parts += ["--", *command]
        self._trace(parts)
        return super().exec(command, **kwargs)


def cli_client(trace: bool = False) -> PebbleCliClient:
    return TracingCliClient() if trace else PebbleCliClient()


# --------------------------------------------------------------------------- #
# The workload — identical code, runs against either client
# --------------------------------------------------------------------------- #
def say(text: str = "") -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    if PACE:
        time.sleep(PACE)


def _find(getter, name: str):
    """Poll ``getter`` until an item named ``name`` appears (or give up)."""
    for _ in range(20):
        for item in getter():
            if item.name == name:
                return item
        time.sleep(0.3)
    raise LookupError(name)


def curl_status(url: str = HTTP_URL) -> str:
    """Return the HTTP status line, retrying while the server comes up."""
    for _ in range(20):
        proc = subprocess.run(
            ["curl", "-s", "-i", "-m", "2", url], capture_output=True, text=True
        )
        first = proc.stdout.splitlines()[0].strip() if proc.stdout else ""
        if first.startswith("HTTP"):
            return first
        time.sleep(0.5)
    return "no response"


def run_workload(client) -> list[str]:
    """Deploy + verify against ``client``; return canonical result lines.

    The result lines are deterministic and transport-independent, so the two
    clients' lists compare equal. Volatile values (change/notice IDs) are shown
    in the live output but kept out of the compared results.
    """
    results: list[str] = []

    say("• deploy: add layer + replan")
    client.add_layer("demo", LAYER, combine=True)
    client.replan_services(timeout=30.0)

    info = client.get_system_info()
    results.append(f"system  : pebble {info.version}")
    say(f"• system info: pebble {info.version}")

    svc = _find(client.get_services, "demo-server")
    results.append(f"service : {svc.name} {svc.current.value} ({svc.startup.value})")
    say(f"• service: {svc.name} is {svc.current.value} (startup {svc.startup.value})")

    chk = _find(client.get_checks, "demo-health")
    results.append(f"check   : {chk.name} level={chk.level.value}")
    say(f"• check: {chk.name} level={chk.level.value}")

    client.make_dir("/tmp/shimmer-demo", make_parents=True)
    client.push("/tmp/shimmer-demo/hello.txt", "Hello from Shimmer!")
    content = client.pull("/tmp/shimmer-demo/hello.txt").read()
    results.append(f"file    : {content!r}")
    say(f"• file round-trip: {content!r}")

    status = curl_status()
    results.append(f"http    : {status}")
    say(f"• GET {HTTP_URL} -> {status}")

    out, _ = client.exec(["echo", "Hello, World!"]).wait_output()
    out = out.strip()
    results.append(f"exec    : {out}")
    say(f"• exec echo -> {out}")

    return results


def run_and_capture(client, results_path: str) -> list[str]:
    """Run the workload, write canonical results to ``results_path``."""
    results = run_workload(client)
    Path(results_path).parent.mkdir(parents=True, exist_ok=True)
    Path(results_path).write_text("\n".join(results) + "\n")
    return results


def deploy_once() -> None:
    """Bring the service up once (used to de-risk the concurrent recording)."""
    client = PebbleCliClient()
    client.add_layer("demo", LAYER, combine=True)
    client.replan_services(timeout=30.0)
    curl_status()


# --------------------------------------------------------------------------- #
# Showboat document
# --------------------------------------------------------------------------- #
def showboat(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["uvx", "showboat", "--workdir", os.getcwd(), *args]
    return subprocess.run(cmd, check=check, capture_output=True, text=True)


def _py(code: str) -> str:
    """Wrap Python so Showboat runs it through uv inside this project."""
    escaped = code.replace("'", "'\\''")
    return f"uv run python3 -c '{escaped}'"


def build_demo() -> bool:
    if os.path.exists(DEMO_FILE):
        os.remove(DEMO_FILE)

    showboat("init", DEMO_FILE, "Shimmer: a drop-in Pebble client over the CLI")

    steps: list[tuple[str, ...]] = [
        ("note",
         "**Shimmer** provides `PebbleCliClient`, a drop-in replacement for "
         "`ops.pebble.Client` that drives Pebble through its **CLI** instead of "
         "the unix socket — for environments where the socket isn't reachable. "
         "The contract is *parity*: same methods, same return types, same "
         "exceptions. This document proves it."),

        ("note", "## The claim, proven"),
        ("note",
         "We run one deploy-and-verify routine against the **real socket "
         "client**, then the **exact same routine** against Shimmer, and compare "
         "the results. First, `ops.pebble.Client` over the unix socket:"),
        ("exec", "bash", _py(
            "from demo import socket_client, run_and_capture\n"
            "run_and_capture(socket_client(), '/tmp/shimmer-parity/socket.txt')")),

        ("note",
         "Now the **same code**, but through `shimmer.PebbleCliClient`. The "
         "dimmed `$ pebble …` lines are the actual commands it shells out:"),
        ("exec", "bash", _py(
            "from demo import cli_client, run_and_capture\n"
            "run_and_capture(cli_client(trace=True), '/tmp/shimmer-parity/cli.txt')")),

        ("note", "## Identical results"),
        ("note",
         "Two transports, one set of outputs. `diff` finds nothing to report:"),
        ("exec", "bash",
         "diff /tmp/shimmer-parity/socket.txt /tmp/shimmer-parity/cli.txt "
         "&& echo 'PARITY: identical ✓'"),

        ("note", "## The service is really running"),
        ("note",
         "The deployed layer runs `python3 -m http.server`. That's a real "
         "process serving real traffic — here's the live response (the "
         "volatile `Date` header is filtered so the document stays verifiable):"),
        ("exec", "bash",
         f"curl -s -i {HTTP_URL} | tr -d '\\r' | grep -vi '^date:' | head -3"),

        ("note", "## Cleanup"),
        ("exec", "bash", _py(
            "from demo import cli_client\n"
            "c = cli_client()\n"
            "c.stop_services(['demo-server'])\n"
            "print('demo-server:', "
            "next(s for s in c.get_services() if s.name == 'demo-server').current.value)")),
    ]

    ok = True
    for step in steps:
        kind, *rest = step
        if kind == "note":
            showboat("note", DEMO_FILE, rest[0])
            say("  note added")
        else:
            lang, code = rest
            result = showboat("exec", DEMO_FILE, lang, code, check=False)
            sys.stdout.write(result.stdout)
            if result.returncode != 0:
                sys.stderr.write(result.stdout)
                say(f"  !! exec failed (rc={result.returncode})")
                ok = False
            else:
                say("  exec ok")
    return ok


# --------------------------------------------------------------------------- #
# tmux side-by-side recording
# --------------------------------------------------------------------------- #
def record_demo() -> None:
    cwd = os.getcwd()
    pebble = os.environ.get("PEBBLE", os.path.expanduser("~/pebble-demo"))
    controller = "/tmp/shimmer-demo-controller.sh"
    driver = "/tmp/shimmer-demo-driver.sh"

    print("Pre-deploying the service so both panes start from a clean, live state ...")
    deploy_once()

    controller_src = f"""#!/usr/bin/env bash
set -u
R={RESULTS_DIR}
echo 'waiting for both clients to finish ...'
for _ in $(seq 1 300); do
  [ -f "$R/.done-socket" ] && [ -f "$R/.done-cli" ] && break
  sleep 0.3
done
echo
echo 'diff of the two clients (canonical results):'
if diff "$R/socket.txt" "$R/cli.txt" > "$R/diff.txt" 2>&1; then
  printf '\\n  \\033[1;32mPARITY: socket and CLI clients produced IDENTICAL results ✓\\033[0m\\n'
else
  printf '\\n  \\033[1;31mDIFFERENCES FOUND:\\033[0m\\n'
  cat "$R/diff.txt"
fi
sleep 6
tmux kill-session -t shimmer 2>/dev/null
"""

    driver_src = f"""#!/usr/bin/env bash
set -u
S=shimmer
R={RESULTS_DIR}
rm -rf "$R"; mkdir -p "$R"
tmux kill-session -t "$S" 2>/dev/null || true
tmux new-session -d -s "$S"
tmux set -g status off
tmux set -g pane-border-status top
tmux set -g pane-border-format ' #{{pane_title}} '
LEFT=$(tmux list-panes -t "$S" -F '#{{pane_id}}' | head -1)
BOTTOM=$(tmux split-window -v -l 10 -P -F '#{{pane_id}}' -t "$LEFT")
RIGHT=$(tmux split-window -h -P -F '#{{pane_id}}' -t "$LEFT")
tmux select-pane -t "$LEFT"   -T 'ops.pebble.Client   (unix socket)'
tmux select-pane -t "$RIGHT"  -T 'shimmer.PebbleCliClient   (CLI)'
tmux select-pane -t "$BOTTOM" -T 'parity check'
RUN="cd {cwd} && PEBBLE={pebble} DEMO_PACE=0.6"
tmux send-keys -t "$LEFT"   "$RUN uv run python demo.py --client socket --results $R/socket.txt; touch $R/.done-socket" C-m
tmux send-keys -t "$RIGHT"  "$RUN uv run python demo.py --client cli    --results $R/cli.txt;    touch $R/.done-cli" C-m
tmux send-keys -t "$BOTTOM" "bash {controller}" C-m
tmux attach -t "$S"
"""

    Path(controller).write_text(controller_src)
    Path(driver).write_text(driver_src)
    os.chmod(controller, 0o755)
    os.chmod(driver, 0o755)

    print(f"Recording tmux side-by-side to {CAST_FILE} ...")
    subprocess.run(
        [
            "asciinema", "rec",
            "--cols", "200", "--rows", "50",
            "--idle-time-limit", "2",
            "--overwrite",
            "--command", f"bash {driver}",
            CAST_FILE,
        ],
        check=True,
    )
    print(f"Recording saved: {CAST_FILE}")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="Shimmer parity demo")
    parser.add_argument("--client", choices=["socket", "cli"],
                        help="run the workload via one client (used by the tmux panes)")
    parser.add_argument("--results", help="write canonical result lines here")
    parser.add_argument("--record", action="store_true",
                        help="record the tmux side-by-side comparison")
    args = parser.parse_args()

    if args.client:
        client = socket_client() if args.client == "socket" else cli_client(trace=True)
        header = ("ops.pebble.Client  (unix socket)" if args.client == "socket"
                  else "shimmer.PebbleCliClient  (CLI)")
        say(f"=== {header} ===\n")
        if args.results:
            run_and_capture(client, args.results)
        else:
            run_workload(client)
        say("\n=== done ===")
        return

    if args.record:
        record_demo()
        return

    print(f"Building {DEMO_FILE} ...")
    if not build_demo():
        print("\nSome steps failed; see output above.", file=sys.stderr)
        sys.exit(1)
    print(f"\nDemo written to {DEMO_FILE}")


if __name__ == "__main__":
    main()
