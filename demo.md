# Shimmer: a drop-in Pebble client over the CLI

*2026-05-28T10:52:26Z by Showboat 0.6.1*
<!-- showboat-id: f59f7e37-3f64-4983-a179-25e547500ba9 -->

**Shimmer** provides `PebbleCliClient`, a drop-in replacement for `ops.pebble.Client` that drives Pebble through its **CLI** instead of the unix socket — for environments where the socket isn't reachable. The contract is *parity*: same methods, same return types, same exceptions. This document proves it.

## The claim, proven

We run one deploy-and-verify routine against the **real socket client**, then the **exact same routine** against Shimmer, and compare the results. First, `ops.pebble.Client` over the unix socket:

```bash
uv run python3 -c 'from demo import socket_client, run_and_capture
run_and_capture(socket_client(), '\''/tmp/shimmer-parity/socket.txt'\'')'
```

```output
• deploy: add layer + replan
• system info: pebble v1.31.0
• service: demo-server is active (startup enabled)
• check: demo-health level=alive
• file round-trip: 'Hello from Shimmer!'
• GET http://localhost:8080 -> HTTP/1.0 200 OK
• exec echo -> Hello, World!
```

Now the **same code**, but through `shimmer.PebbleCliClient`. The dimmed `$ pebble …` lines are the actual commands it shells out:

```bash
uv run python3 -c 'from demo import cli_client, run_and_capture
run_and_capture(cli_client(trace=True), '\''/tmp/shimmer-parity/cli.txt'\'')'
```

```output
• deploy: add layer + replan
    [2m$ pebble add demo /tmp/<tmp>.yaml --combine[0m
    [2m$ pebble replan --no-wait[0m
    [2m$ pebble tasks <id> --format json[0m
    [2m$ pebble version --client[0m
• system info: pebble v1.31.0
    [2m$ pebble services --format json[0m
• service: demo-server is active (startup enabled)
    [2m$ pebble checks --format json[0m
• check: demo-health level=alive
    [2m$ pebble mkdir /tmp/shimmer-demo -p[0m
    [2m$ pebble push /tmp/<tmp> /tmp/shimmer-demo/hello.txt[0m
    [2m$ pebble pull /tmp/shimmer-demo/hello.txt /tmp/<tmp>[0m
• file round-trip: 'Hello from Shimmer!'
• GET http://localhost:8080 -> HTTP/1.0 200 OK
    [2m$ pebble exec -- echo Hello, World![0m
• exec echo -> Hello, World!
```

## Identical results

Two transports, one set of outputs. `diff` finds nothing to report:

```bash
diff /tmp/shimmer-parity/socket.txt /tmp/shimmer-parity/cli.txt && echo 'PARITY: identical ✓'
```

```output
PARITY: identical ✓
```

## The service is really running

The deployed layer runs `python3 -m http.server`. That's a real process serving real traffic — here's the live response (the volatile `Date` header is filtered so the document stays verifiable):

```bash
curl -s -i http://localhost:8080 | tr -d '\r' | grep -vi '^date:' | head -3
```

```output
HTTP/1.0 200 OK
Server: SimpleHTTP/0.6 Python/3.12.3
Content-type: text/html; charset=utf-8
```

## Cleanup

```bash
uv run python3 -c 'from demo import cli_client
c = cli_client()
c.stop_services(['\''demo-server'\''])
print('\''demo-server:'\'', next(s for s in c.get_services() if s.name == '\''demo-server'\'').current.value)'
```

```output
demo-server: inactive
```
