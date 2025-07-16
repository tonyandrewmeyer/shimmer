# Development

## Setup Development Environment

```bash
# Clone repository
git clone https://github.com/tonyandewmeyer/shimmer
cd shimmer

# Install with development dependencies
uv sync

# Install pre-commit hooks
pre-commit install
```

## Running Tests

Shimmer includes comprehensive test suites with multiple test types:

### Quick Start

```bash
# Install with development dependencies
uv sync

# Run unit tests (fast, no external dependencies)
tox -e unit

# Run integration tests only (requires Pebble)
tox -e integration

# Run all tests including integration
tox -e unit,integration
```

### Environment Variables

```bash
# Custom Pebble directory
export PEBBLE=/custom/pebble/dir

# Custom Pebble binary
export PEBBLE_BINARY=/snap/bin/pebble
```

### Debugging Integration Tests

**Verbose Output:**
```bash
pytest tests/test_integration.py -v -s --tb=long
```

**Keep Test Environment:**
```bash
python run_tests.py integration --no-cleanup
```

**Debug Specific Test:**
```bash
pytest tests/test_integration.py::TestCommandExecution::test_exec_with_stdin -v -s
```

**Manual Pebble Setup:**
```bash
# Start Pebble manually for debugging
export PEBBLE=/tmp/debug-pebble
mkdir -p $PEBBLE/layers
pebble run --hold &

# Run tests against manual setup
pytest tests/test_integration.py::TestSystemIntegration::test_system_info -v
```

### Performance Benchmarking

```bash
# Run performance tests with timing
pytest tests/test_integration.py::TestPerformance -v --durations=10

# Profile specific operations
python -m pytest tests/test_integration.py::TestPerformance::test_concurrent_operations --profile
```

### Troubleshooting

**Common Issues:**

1. **"Pebble binary not found"**
   ```bash
   # Check PATH
   which pebble
   
   # Install via snap
   sudo snap install pebble
   
   # Or specify custom path
   export PEBBLE_BINARY=/usr/local/bin/pebble
   ```

2. **"Connection refused"**
   ```bash
   # Check if Pebble is running
   pebble version
   
   # Kill existing instances
   pkill pebble
   ```

3. **"Tests timeout"**
   ```bash
   # Increase timeout
   pytest tests/ -m integration --timeout=120
   ```

### Contributing Test Cases

When adding new functionality:

1. **Add unit tests** for the core logic
2. **Add integration tests** for end-to-end functionality  
3. **Update test documentation** if needed
4. **Ensure CI passes** before submitting PR

## Code Quality

This project uses several tools to maintain code quality:

- **ruff** - Fast Python linter and formatter
- **ty** - Static type checker
- **pytest** - Testing framework
- **pre-commit** - Git hooks for quality checks
- **tox** - Test automation

```bash
# Format code
tox -e format

# Run linting, including type checking
tox -e lint
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes
4. Run tests: `tox`
5. Submit a pull request

### Guidelines

- Maintain 100% API compatibility with `ops.pebble.Client`
- Add tests for new functionality
- Update documentation as needed
- Follow existing code style (enforced by ruff)
- Ensure type safety (checked by pyright)
