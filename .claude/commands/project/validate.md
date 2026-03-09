---
name: validate
description: Run lint and test checks to validate project state
arguments: $1
---

# Validate

Run all validation checks: linting, formatting, and tests.

## Execution

### Step 1: Run Lint

```bash
python3 -m ruff check nautobot_route_tracking/ tests/
```

Collect all lint errors. Do not stop on first error.

### Step 2: Run Format Check

```bash
python3 -m ruff format --check nautobot_route_tracking/ tests/
```

### Step 3: Run Tests

Tests run inside the Docker container:

```bash
for c in nautobot nautobot-worker nautobot-scheduler; do
  docker exec $c rm -rf /tmp/nautobot_route_tracking
  docker cp ./nautobot_route_tracking $c:/tmp/nautobot_route_tracking
  docker exec $c pip install --force-reinstall --no-deps /tmp/nautobot_route_tracking
done
docker exec nautobot nautobot-server makemigrations nautobot_route_tracking --check
docker cp ./tests nautobot:/tmp/tests
docker exec nautobot bash -c "cd /tmp && python -m pytest tests/ -v --tb=short"
```

### Step 4: Optional Scope Filter

If `$1` is provided, limit lint to that scope:

```bash
python3 -m ruff check $1
```

### Step 5: Summary

```text
=== Validation Summary ===
Target: $1 (or "all")

Lint:  X errors, Y warnings
Tests: X passed, Y failed, Z skipped

Status: PASS / FAIL
```

## On Failure

Display each error clearly. Do NOT proceed to commit or deploy until all checks pass.
