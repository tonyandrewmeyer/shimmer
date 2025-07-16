# Shimmer - shiny Pebble client

A 100% compatible drop-in replacement for `ops.pebble.Client` that uses the Pebble CLI tool instead of socket communication.

## Overview

Shimmer provides `PebbleCliClient`, a class that implements the same interface as `ops.pebble.Client` but communicates with Pebble via CLI commands instead of socket communication. This is useful for environments with restricted socket access (such as a Rock or Juju container).

## Installation

### Install from PyPI

```bash
uv pip install shimmer
```

### Install development version
```bash
git clone https://github.com/tonyandrewmeyer/shimmer
cd shimmer
uv pip install -e .
```

## Quick Start

```python
from shimmer import PebbleCliClient as Client

# Create a client instance:
client = Client(
    socket_path="/var/lib/pebble/default/.pebble.socket",  # Optional: for env setup
    pebble_binary="pebble",  # Path to pebble binary
    timeout=30.0,  # Default command timeout
)

# Use exactly like ops.pebble.Client:
services = client.get_services()
client.start_services(["myservice"])

# Execute commands:
process = client.exec(["echo", "hello world"])
stdout, stderr = process.wait_output()
print(stdout)  # "hello world\n"

# File operations:
client.push("/path/to/file", "content")
content = client.pull("/path/to/file").read()

# Layer management
layer = """
services:
  myservice:
    override: replace
    command: python3 -m http.server 8080
    startup: enabled
"""
client.add_layer("mylayer", layer)
client.replan_services()
```

## Advanced Usage

### Custom Binary Path

```python
client = PebbleCliClient(pebble_binary="/usr/local/bin/pebble")
```

### Environment Configuration

```python
# If using custom Pebble directory:
client = PebbleCliClient(socket_path="/custom/path/.pebble.socket")

# This automatically sets:
# PEBBLE=/custom/path
# PEBBLE_SOCKET=/custom/path/.pebble.socket
```

### Error Handling

```python
from shimmer import APIError, ConnectionError, TimeoutError

try:
    client.start_services(["nonexistent"])
except APIError as e:
    print(f"API Error: {e.message} (code: {e.code})")
except ConnectionError:
    print("Could not connect to Pebble")
except TimeoutError:
    print("Operation timed out")
```

### Process Execution

```python
# Simple command:
process = client.exec(["ls", "-la"])
stdout, stderr = process.wait_output()

# With environment and options:
process = client.exec(
    ["python3", "script.py"],
    environment={"PYTHONPATH": "/app"},
    working_dir="/app",
    timeout=60.0,
    user="appuser",
)

# Streaming I/O:
process = client.exec(["cat"], stdin="Hello World\n")
stdout, stderr = process.wait_output()
```

## Architecture

The `PebbleCliClient` works by:

1. **Command Translation** - Converts API calls to CLI commands
2. **Output Parsing** - Parses CLI output back to Python objects
3. **Error Mapping** - Maps CLI errors to compatible exceptions
4. **Process Management** - Handles subprocess execution and I/O

## Limitations

While this client aims for 100% compatibility, there are some limitations due to CLI constraints:

1. **Performance** - CLI calls have higher overhead than socket communication
2. **Concurrency** - Each operation spawns a new process
3. **Streaming** - Some streaming operations may be buffered
4. **Platform** - Requires Pebble binary in PATH or specified location

Other minor limitations:

- `replan_services()`, `start_services()`, `stop_services()`, and `restart_services()` are only able to return the change ID if no timeout is set.
- `notify()` only supports custom notices.
- `get_notices()` cannot include the `last_occurred`, `last_data`, `repeat_after`, or `expire_after` fields
- `get_changes()` cannot include the `kind`, `tasks`, `err`, `ready_time`, or `data` fields, and guesses at the `ready` field
- `autostart_services()` is an alias for `replan()` (possibly we could fix this by getting the current state?)
- `wait_change()` is yet to be implemented
- `ack_warnings()` is yet to be implemented
- `get_warnings()` is only implemented for the 'no warnings' case
- `list_file()` looks up the user and group IDs locally, which is very likely to be wrong
- `get_identities()` is unable to get the user ID for local identities

## Comparison with ops.pebble.Client

| Feature | ops.pebble.Client | PebbleCliClient |
|---------|------------------|-----------------|
| Communication | Unix socket | CLI commands |
| Performance | High | Moderate |
| Setup | Requires socket access | Requires binary |
| Compatibility | Native | 100% API compatible |
| Dependencies | ops library | ops library + CLI |
| Use Cases | Production charms | Testing, development, debugging |

## Examples

### Service Management

```python
from shimmer import PebbleCliClient as Client

client = Client()

# Get all services:
services = client.get_services()
for service in services:
    print(f"{service.name}: {service.current}")

# Start specific services:
change_id = client.start_services(["web", "db"])
print(f"Started services, change: {change_id}")

# Wait for change to complete:
change = client.wait_change(change_id)
print(f"Change {change.id} status: {change.status}")
```

### File Management

```python
# Create directory structure:
client.make_dir("/app/config", make_parents=True, permissions=0o755)

# Write configuration file:
config = """
server:
  port: 8080
  host: 0.0.0.0
"""
client.push("/app/config/server.yaml", config)

# Read file back:
content = client.pull("/app/config/server.yaml").read()
print(content)

# List directory contents:
files = client.list_files("/app/config")
for file in files:
    print(f"{file.name} ({file.type})")
```

### Layer Management

```python
# Define service layer:
layer = {
    "summary": "Web application layer",
    "description": "Defines the web application service",
    "services": {
        "webapp": {
            "override": "replace",
            "summary": "Web application",
            "command": "python3 -m uvicorn app:main --host 0.0.0.0 --port 8080",
            "startup": "enabled",
            "environment": {
                "PYTHONPATH": "/app"
            },
            "user": "webapp",
            "group": "webapp",
        }
    },
    "checks": {
        "webapp-health": {
            "override": "replace",
            "level": "alive",
            "http": {"url": "http://localhost:8080/health"},
            "period": "10s",
            "timeout": "3s",
            "threshold": 3,
        }
    }
}

# Add and apply layer:
client.add_layer("webapp", layer)
change_id = client.replan_services()

# Wait for services to start:
client.wait_change(change_id)

# Check service status:
services = client.get_services(["webapp"])
print(f"webapp status: {services[0].current}")
```

### Command Execution

```python
# Execute simple command:
process = client.exec(["whoami"])
stdout, stderr = process.wait_output()
print(f"Running as: {stdout.strip()}")

# Execute with service context:
process = client.exec(
    ["python3", "-c", "import os; print(os.getcwd())"],
    service_context="webapp"
)
stdout, stderr = process.wait_output()
print(f"Service working directory: {stdout.strip()}")

# Execute interactive command:
process = client.exec(["python3", "-c", "print(input('Name: '))"])
process.stdin.write("Alice\n")
process.stdin.close()
stdout, stderr = process.wait_output()
print(f"Output: {stdout.strip()}")
```

### Health Checks

```python
# Get all checks:
checks = client.get_checks()
for check in checks:
    print(f"{check.name}: {check.status} ({check.level})")

# Start specific checks:
started = client.start_checks(["webapp-health"])
print(f"Started checks: {started}")

# Monitor check status:
import time
for _ in range(5):
    checks = client.get_checks(names=["webapp-health"])
    if checks:
        check = checks[0]
        print(f"Check status: {check.status}, failures: {check.failures}")
    time.sleep(2)
```

### Notice Management

```python
# Get recent notices:
notices = client.get_notices()
for notice in notices:
    print(f"{notice.type}: {notice.key} (occurred: {notice.occurrences})")

# Create custom notice:
notice_id = client.notify(
    type="custom",
    key="myapp.com/deployment",
    data={"version": "1.2.3", "environment": "production"}
)
print(f"Created notice: {notice_id}")

# Get specific notice:
notice = client.get_notice(notice_id)
print(f"Notice data: {notice.last_data}")
```

## Troubleshooting

### Common Issues

1. **"Pebble binary not found"**
   ```python
   # Specify full path to pebble
   client = PebbleCliClient(pebble_binary="/snap/bin/pebble")
   ```

2. **"Permission denied"**
   ```bash
   # Ensure user has access to Pebble directory
   sudo chown -R $USER:$USER $PEBBLE
   ```

3. **"Connection error"**
   ```python
   # Check if Pebble is running
   import subprocess
   result = subprocess.run(["pebble", "version"], capture_output=True)
   print(result.stdout)
   ```

### Debugging

Enable debug logging to see CLI commands:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

# Commands will be logged before execution:
client = PebbleCliClient()
services = client.get_services()
```

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and changes.

## Related Projects

- [ops](https://ops.readthedocs.io) - The operator framework
- [pebble](https://documentation.ubuntu.com/pebble) - The Pebble service manager
- [juju](https://juju.is) - Juju
- [charmcraft](https://canonical-charmcraft.readthedocs-hosted.com) - Juju charm development tools
- [rockcraft](https://documentation.ubuntu.com/rockcraft) - Rock development tools
