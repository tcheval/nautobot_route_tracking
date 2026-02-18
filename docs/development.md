# Development Guide

This guide covers local setup, testing, linting, and conventions for contributing to **nautobot-route-tracking**.

## Local setup

### Prerequisites

- Python 3.10 or later
- [Poetry](https://python-poetry.org/) (recommended) or pip
- PostgreSQL or SQLite (SQLite is used automatically in development and tests)
- Redis (required for Celery; can be skipped for unit tests with the in-memory cache backend)

### Clone and install

```bash
git clone https://github.com/tcheval/nautobot_route_tracking
cd nautobot_route_tracking
poetry install
```

### Initialize Nautobot configuration

```bash
poetry run nautobot-server init
```

This generates `~/.nautobot/nautobot_config.py`. Open it and add the plugin:

```python
PLUGINS = [
    "nautobot_plugin_nornir",
    "nautobot_route_tracking",
]

PLUGINS_CONFIG = {
    "nautobot_plugin_nornir": {
        "use_config_context": {"connection_options": True},
    },
    "nautobot_route_tracking": {
        "route_retention_days": 90,
        "nornir_workers": 50,
        "device_timeout": 30,
    },
}
```

### Run migrations

```bash
poetry run nautobot-server migrate
```

### Create a superuser

```bash
poetry run nautobot-server createsuperuser
```

### Start the development server

```bash
poetry run nautobot-server runserver
```

Navigate to `http://localhost:8080` and log in with the superuser credentials.

---

## Running tests

### Full test suite with coverage

```bash
poetry run pytest --cov=nautobot_route_tracking --cov-report=html
```

The HTML coverage report is generated in `htmlcov/index.html`. The minimum required coverage is **80%** (enforced via `[tool.coverage.report] fail_under = 80` in `pyproject.toml`).

### Run a specific test file

```bash
poetry run pytest tests/test_models.py -v
poetry run pytest tests/test_jobs.py -v
poetry run pytest tests/test_filters.py -v
poetry run pytest tests/test_api.py -v
```

### Run a specific test by name

```bash
poetry run pytest tests/test_models.py::TestRouteEntry::test_unique_constraint_ecmp -v
```

---

## Code formatting and linting

This project uses [Ruff](https://docs.astral.sh/ruff/) as the single tool for both formatting and linting (replaces Black + flake8 + isort).

### Format all code

```bash
poetry run ruff format nautobot_route_tracking tests
```

### Check linting without fixing

```bash
poetry run ruff check nautobot_route_tracking tests
```

### Fix auto-fixable issues and format

```bash
poetry run ruff check nautobot_route_tracking tests --fix
poetry run ruff format nautobot_route_tracking tests
```

All code must pass `ruff check` and `ruff format --check` with zero errors before committing.

---

## Database migrations

### Create a new migration after model changes

```bash
poetry run nautobot-server makemigrations nautobot_route_tracking
```

### Apply migrations

```bash
poetry run nautobot-server migrate
```

### Verify no pending migrations exist

```bash
poetry run nautobot-server makemigrations nautobot_route_tracking --check
```

Use this in CI to ensure no unapplied model changes are present.

**Conventions for migrations**:

- One migration per logical change. Do not mix schema and data migrations.
- Data migrations must include a `reverse_code` (or `migrations.RunPython.noop` with a comment if irreversible).
- Never modify a migration that has already been applied in production. Create a new migration instead.

---

## Test architecture

### `tests/conftest.py` — shared fixtures

Contains pytest fixtures used across all test modules. All fixtures use `validated_save()`, not `.create()` or `.save()`, to exercise the same model validation as production code.

Key fixtures:

| Fixture | Returns | Notes |
| ------- | ------- | ----- |
| `status_active` | `Status` | "Active" status from Nautobot |
| `location` | `Location` | A test location (Geneva-DC1) |
| `role` | `Role` | A test device role (Router) |
| `manufacturer` | `Manufacturer` | A test manufacturer |
| `device_type` | `DeviceType` | A test device type |
| `platform_eos` | `Platform` | Arista EOS platform with `network_driver="arista_eos"` and `napalm_driver="eos"` |
| `device` | `Device` | A test device with platform and location |
| `vrf` | `VRF` | An optional test VRF |
| `interface` | `Interface` | An interface on the test device |
| `route_entry` | `RouteEntry` | A single OSPF route entry on the test device |

### `tests/factories.py` — Factory Boy factories

Factory Boy factories for generating test data programmatically. Use these in tests that need multiple objects or complex data sets.

```python
from tests.factories import DeviceFactory, RouteEntryFactory

def test_bulk_routes():
    device = DeviceFactory()
    routes = RouteEntryFactory.create_batch(10, device=device, protocol="ospf")
    assert len(routes) == 10
```

Available factories:

| Factory | Model |
| ------- | ----- |
| `DeviceFactory` | `dcim.Device` |
| `VRFFactory` | `ipam.VRF` |
| `RouteEntryFactory` | `nautobot_route_tracking.RouteEntry` |

### `tests/test_models.py` — model validation and NetDB logic

Tests for:

- Model field validation (e.g., valid network prefix format, non-empty next_hop for non-CONNECTED routes)
- UniqueConstraint enforcement: two entries with the same `(device, vrf, network, next_hop, protocol)` must fail
- ECMP: two entries with the same `(device, vrf, network, protocol)` but different `next_hop` must both succeed
- NetDB UPDATE logic: calling the collection handler twice with the same route updates `last_seen` without creating a duplicate
- NetDB INSERT logic: a route with a changed `next_hop` creates a new record

### `tests/test_jobs.py` — Nornir mock and job execution

Tests for the `CollectRoutingTablesJob` and `PurgeOldRoutesJob` with mocked Nornir:

```python
from unittest.mock import MagicMock, patch

@patch("nautobot_route_tracking.jobs._base.InitNornir")
def test_job_commit_mode(self, mock_init_nornir, device):
    mock_nr = MagicMock()
    mock_nr.inventory.hosts = {device.name: MagicMock()}
    mock_init_nornir.return_value = mock_nr

    # Mock nr.run() — not nr.filter().run()
    mock_host_result = MagicMock()
    mock_host_result.failed = False
    mock_host_result.result = {
        "routes": {
            "10.0.0.0/8": [
                {
                    "protocol": "OSPF",
                    "current_active": True,
                    "next_hop": "192.168.1.1",
                    "outgoing_interface": "Ethernet1",
                    "preference": 110,
                    "routing_table": "default",
                    "protocol_attributes": {"metric": 20},
                }
            ]
        }
    }
    mock_nr.run.return_value = {device.name: mock_host_result}
    ...
```

Key scenarios to test:

- UPDATE vs INSERT NetDB logic on second collection run
- ECMP: multiple next-hops for the same prefix result in multiple separate records
- Excluded prefixes: multicast and link-local prefixes are never stored
- Protocol normalization: `"OSPF"` from EOS is stored as `"ospf"`
- Partial failure: one device fails, job still succeeds and logs the failure
- Total failure: all devices fail, job raises `RuntimeError`
- Dry-run: `commit=False` collects data and logs results but writes nothing to the database

### `tests/test_filters.py` — FilterSet inputs

Tests for `RouteEntryFilterSet`. FK filters (`device`, `vrf`) are `NaturalKeyOrPKMultipleChoiceFilter` and require list input:

```python
# Correct: FK filter values wrapped in a list
filterset = RouteEntryFilterSet({"device": [str(device.pk)]})
assert filterset.is_valid()
assert filterset.qs.count() == expected_count

# Correct: CharFilter fields use bare strings
filterset = RouteEntryFilterSet({"network": "10.0"})
assert filterset.is_valid()
```

### `tests/test_api.py` — REST API endpoints

Tests for the CRUD API endpoints. Use hardcoded URL paths instead of `reverse()` with nested namespaces, which can be fragile in test environments:

```python
_API_BASE = "/api/plugins/route-tracking"

def _routes_list_url():
    return f"{_API_BASE}/routes/"

def _routes_detail_url(pk):
    return f"{_API_BASE}/routes/{pk}/"
```

Test cases:

- `GET /api/plugins/route-tracking/routes/` — list with pagination
- `GET /api/plugins/route-tracking/routes/<uuid>/` — detail
- `GET .../routes/?device=<name>&protocol=ospf` — filtered list
- `GET .../routes/?network=10.0` — partial network match
- Unauthenticated requests return 403

---

## Code conventions

### Type hints

Use Python 3.10+ native syntax throughout. The old `Optional[X]` and `Union[X, Y]` forms are forbidden:

```python
# Correct
def find_route(network: str, device: Device) -> RouteEntry | None: ...
def get_devices(filters: dict[str, Any]) -> list[Device]: ...

# Forbidden
from typing import Optional, Union
def find_route(network: str, device: Device) -> Optional[RouteEntry]: ...
```

### Docstrings

Google-style docstrings on all public functions and classes:

```python
def process_route_results(device: Device, routes: dict[str, list]) -> dict[str, int]:
    """Process collected route entries and apply NetDB UPDATE/INSERT logic.

    Args:
        device: Nautobot Device instance.
        routes: Dict of prefix -> list of next-hop dicts, as returned by get_route_to().

    Returns:
        Dict with keys: {"updated": int, "created": int, "errors": int}.

    Raises:
        ValidationError: If a route entry fails model validation.

    Example:
        >>> result = process_route_results(device, {"10.0.0.0/8": [{"next_hop": "..."}]})
        >>> print(result)
        {'updated': 5, 'created': 2, 'errors': 0}

    """
```

### `validated_save()` — always

Never call `.save()` or `objects.create()` directly. Always use `instance.validated_save()`. This ensures Nautobot's `full_clean()` runs and custom model validation is enforced:

```python
# Forbidden
entry.save()
RouteEntry.objects.create(device=device, ...)

# Required
entry = RouteEntry(device=device, network="10.0.0.0/8", ...)
entry.validated_save()
```

### Error handling

Never catch `Exception` silently. Always log before continuing:

```python
# Forbidden
try:
    result = task.run(task=collect_routes_task)
except Exception:
    pass

# Required
try:
    result = task.run(task=collect_routes_task)
except Exception:
    host.logger.warning("Route collection subtask failed", exc_info=True)
```

In Nornir jobs, per-device failures must not abort the entire job. Only raise `RuntimeError` when zero devices succeeded:

```python
# Only fail the entire job on complete infrastructure failure
if stats["devices_success"] == 0 and stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)
```

### Logging

Use `logging.getLogger(__name__)` and lazy `%s` formatting (not f-strings) in logger calls:

```python
import logging
logger = logging.getLogger(__name__)

# Correct — lazy formatting
logger.info("Device %s: collected %d routes", device.name, route_count)
logger.error("Collection failed for %s: %s", device_name, error_msg)

# Forbidden in logger calls — f-string is evaluated even if log level is disabled
logger.info(f"Device {device.name} updated")
```

---

## Commit conventions

This project uses [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add VRF filter to collection job
fix: normalize protocol to lowercase before storage
docs: update usage guide with BGP warning
refactor: extract route processing logic to utils module
test: add ECMP test cases to test_models
```

Commits must be atomic: one logical change per commit.

---

## Swarm mode (parallel agent execution)

For large refactoring tasks or feature implementations that touch multiple independent modules, use the **swarm mode** pattern: launch multiple Claude agents in parallel via the `Task` tool.

### When to use swarm

- Multi-file refactoring (models + views + tables + filters + templates)
- Adding tests for multiple independent modules simultaneously
- Implementing independent features in parallel
- Exploratory research across multiple domains

### When not to use swarm

- Sequential tasks with dependencies (migration before tests, model before view)
- Modifications to a single file
- Trivial tasks (fewer than 3 steps)

### Example: adding tests in parallel

```
Agent 1: Write tests/test_models.py — validation, constraints, NetDB UPDATE/INSERT
Agent 2: Write tests/test_filters.py — FK filter inputs, CharFilter inputs
Agent 3: Write tests/test_api.py — list, detail, filtered endpoints, auth
```

Each agent reads the existing source files before writing tests. No two agents modify the same file.

---

## References

- [Nautobot App Development Guide](https://docs.nautobot.com/projects/core/en/stable/development/apps/)
- [nautobot-plugin-nornir documentation](https://docs.nautobot.com/projects/plugin-nornir/en/latest/)
- [Network-to-Code Cookiecutter](https://github.com/nautobot/cookiecutter-nautobot-app)
- [NAPALM `get_route_to()` documentation](https://napalm.readthedocs.io/en/latest/base.html#napalm.base.base.NetworkDriver.get_route_to)
- [Nornir documentation](https://nornir.readthedocs.io/)
- [Ruff documentation](https://docs.astral.sh/ruff/)
- [Factory Boy documentation](https://factoryboy.readthedocs.io/)
- [Conventional Commits specification](https://www.conventionalcommits.org/)
