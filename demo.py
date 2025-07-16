#!/usr/bin/env python

"""Demo script showing Shimmer usage.

This script demonstrates how to use Shimmer as a drop-in replacement
for ops.pebble.Client. It includes examples of common operations.
"""

import sys
import time

import ops

from shimmer import PebbleCliClient as Client


def demo_system_info(client: Client):
    """Demonstrate system information retrieval."""
    print("=== System Information ===")
    try:
        info = client.get_system_info()
        print(f"Pebble version: {info.version}")
    except Exception as e:
        print(f"Error getting system info: {e}")
    print()


def demo_layer_management(client: Client):
    """Demonstrate layer management."""
    print("=== Layer Management ===")

    layer = """
summary: Demo web server
description: A simple HTTP server for demonstration
services:
  demo-server:
    override: replace
    summary: Demo HTTP server
    command: python3 -m http.server 8080
    startup: enabled
    environment:
      PYTHONPATH: /app
checks:
  demo-health:
    override: replace
    level: alive
    http:
      url: http://localhost:8080
    period: 30s
    timeout: 3s
    threshold: 3
"""

    try:
        print("Adding demo layer...")
        client.add_layer("demo", layer)
        print("✓ Layer added successfully")

        print("Getting current plan...")
        plan = client.get_plan()
        print(f"✓ Plan has {len(plan.services)} services and {len(plan.checks)} checks")

        print("Replanning services...")
        change_id = client.replan_services(timeout=30.0)
        print(f"✓ Replan completed, change ID: {change_id}")
    except Exception as e:
        print(f"Error in layer management: {e}")
    print()


def demo_service_management(client: Client):
    """Demonstrate service management."""
    print("=== Service Management ===")

    try:
        print("Getting service status...")
        services = client.get_services()

        if services:
            for service in services:
                print(f"  {service.name}: {service.current} (startup: {service.startup})")

            first_service = services[0]
            if first_service.current != "active":
                print(f"Starting service: {first_service.name}")
                change_id = client.start_services([first_service.name])
                print(f"✓ Start initiated, change ID: {change_id}")
            else:
                print(f"✓ Service {first_service.name} is already active")
        else:
            print("No services found")
    except Exception as e:
        print(f"Error in service management: {e}")
    print()


def demo_file_operations(client: Client):
    """Demonstrate file operations."""
    print("=== File Operations ===")

    try:
        print("Creating directory...")
        client.make_dir("/tmp/pebble-demo", make_parents=True)
        print("✓ Directory created")

        print("Writing file...")
        content = "Hello from Shimmer!\nTimestamp: " + str(time.time())
        client.push("/tmp/pebble-demo/test.txt", content)
        print("✓ File written")

        print("Reading file...")
        file_content = client.pull("/tmp/pebble-demo/test.txt").read()
        print(f"✓ File content: {repr(file_content[:50])}...")

        print("Listing directory...")
        files = client.list_files("/tmp/pebble-demo")
        for file in files:
            print(f"  {file.name} ({file.type})")
    except Exception as e:
        print(f"Error in file operations: {e}")
    print()


def demo_command_execution(client: Client):
    """Demonstrate command execution."""
    print("=== Command Execution ===")

    try:
        print("Executing simple command...")
        process = client.exec(["echo", "Hello, World!"])
        stdout, stderr = process.wait_output()
        print(f"✓ Output: {stdout.strip()}")

        print("Executing command with environment...")
        process = client.exec(
            ["python3", "-c", "import os; print(f'USER: {os.environ.get(\"USER\", \"unknown\")}')"],
            environment={"USER": "demo-user"}
        )
        stdout, _ = process.wait_output()
        print(f"✓ Output: {stdout.strip()}")

        print("Executing command that might fail...")
        try:
            process = client.exec(["ls", "/nonexistent"])
            stdout, stderr = process.wait_output()
            print(f"✓ Unexpected success: {stdout}")
        except Exception as e:
            print(f"✓ Expected error: {type(e).__name__}")
    except Exception as e:
        print(f"Error in command execution: {e}")
    print()


def demo_health_checks(client: Client):
    """Demonstrate health check management."""
    print("=== Health Checks ===")

    try:
        print("Getting check status...")
        checks = client.get_checks()

        if checks:
            for check in checks:
                print(f"  {check.name}: {check.status} (level: {check.level})")

            check_names = [check.name for check in checks]
            print(f"Starting checks: {check_names}")
            started = client.start_checks(check_names)
            print(f"✓ Started checks: {started}")
        else:
            print("No checks found")
    except Exception as e:
        print(f"Error in health checks: {e}")
    print()


def demo_notices(client: Client):
    """Demonstrate notice management."""
    print("=== Notices ===")

    try:
        print("Creating custom notice...")
        notice_id = client.notify(
            type=ops.pebble.NoticeType.CUSTOM,
            key="demo.example.com/test",
            data={"message": "Demo notice from Shimmer", "timestamp": str(time.time())}
        )
        print(f"✓ Created notice: {notice_id}")

        print("Getting notices...")
        notices = client.get_notices()

        for notice in notices:
            print(f"  {notice.id}: {notice.type} - {notice.key}")
            if notice.last_data:
                print(f"    Data: {notice.last_data}")
    except Exception as e:
        print(f"Error in notices: {e}")
    print()


def main():
    """Main demo function."""
    print("Shimmer Demo")
    print("=" * 50)

    pebble_options = {
        None: "default configuration",
        "/snap/bin/pebble": "snap installation",
        "/usr/local/bin/pebble": "custom path",
    }

    for pebble_binary, desc in pebble_options.items():
        try:
            print(f"Attempting to connect with {desc}...")
            client = Client(pebble_binary=pebble_binary) if pebble_binary else Client()
            client.get_system_info()
            print(f"✓ Connected successfully with {desc}")
            break
        except ops.pebble.ConnectionError:
            print(f"✗ {desc.capitalize()} not found")
            client = None
    else:
        print("✗ Could not find pebble binary anywhere")
        print("\nTo run this demo, please ensure pebble is installed:")
        print("  - sudo snap install pebble")
        print("  - or install from https://github.com/canonical/pebble")
        sys.exit(1)

    print()

    demo_system_info(client)
    demo_layer_management(client)
    demo_service_management(client)
    demo_file_operations(client)
    demo_command_execution(client)
    demo_health_checks(client)
    demo_notices(client)

    print("Demo completed successfully!")


if __name__ == "__main__":
    main()
