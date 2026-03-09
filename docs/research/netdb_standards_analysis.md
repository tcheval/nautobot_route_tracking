# NetDB Standards Analysis — nautobot_netdb_tracking Reference

**Generated**: 2026-02-18
**Source plugin**: `nautobot-netdb-tracking` v1.0.0
**Purpose**: Reference document for implementing `nautobot_route_tracking` following the exact same standards, patterns, and conventions.

---

## Table of Contents

1. [Code Standards](#1-code-standards)
2. [Architecture Principles](#2-architecture-principles)
3. [Pitfalls Nautobot 3.x — Complete and Verbatim](#3-pitfalls-nautobot-3x--complete-and-verbatim)
4. [Testing Patterns](#4-testing-patterns)
5. [Plugin Configuration](#5-plugin-configuration)
6. [pyproject.toml — Exact Configuration](#6-pyprojecttoml--exact-configuration)
7. [Swarm Mode Patterns](#7-swarm-mode-patterns)

---

## 1. Code Standards

Sources: `CLAUDE.md`, `SPECS.md`, `docs/nautobot_plugin_dev_lessons.md`

### 1.1 `validated_save()` vs `.save()` — Absolute Rule

**Rule**: Never use `.save()` directly. Always use `.validated_save()`.

**Explanation**: `validated_save()` is the Nautobot method that calls `full_clean()` then `save()`. It guarantees:

- Execution of `clean()` (custom model validation)
- Execution of Django validations (`validate_unique`, `validate_constraints`)
- Compliance with Nautobot constraints (custom fields, tags, etc.)

```python
# NEVER
mac.save()
MACAddressHistory.objects.create(...)

# ALWAYS
mac.validated_save()

# Pattern update_or_create_entry (NetDB logic)
instance = MACAddressHistory(device=device, interface=interface, ...)
instance.validated_save()
```

**Known exception**: The `grouping` field of a Job is overwritten by `validated_save()`. To modify it, use `QuerySet.update()`:

```python
Job.objects.filter(module_name__startswith="nautobot_netdb_tracking").update(
    enabled=True, grouping="NetDB Tracking"
)
```

**Rule for test fixtures**: Fixtures must also use `validated_save()`, not `.create()` or `.save()`, to exercise the same validations as in production.

### 1.2 Type Hints — Required, Python 3.10+ Format

**Required format**: Python 3.10+ native syntax (PEP 604).

```python
# Python 3.10+ — use these forms
def get_devices(filters: dict[str, Any]) -> list[Device]: ...
def find_mac(mac: str | None) -> MACAddressHistory | None: ...
def process_results(device: Device, entries: list[dict]) -> dict[str, int]: ...

# FORBIDDEN — old-style Optional
from typing import Optional
def find_mac(mac: Optional[str]) -> Optional[MACAddressHistory]: ...
```

**Rules**:

- Annotate all parameters and return types of public functions
- Use `TypedDict` for complex data structures passed as dicts
- Use `typing.Protocol` rather than inheritance for duck typing
- Import `Any` from `typing` when necessary

### 1.3 Docstrings — Google Style, Required Sections

**Style**: Google style docstrings on all public functions/classes.

```python
def process_mac_results(device: Device, mac_entries: list[dict]) -> dict[str, int]:
    """Process collected MAC entries and apply NetDB UPDATE/INSERT logic.

    Args:
        device: Nautobot Device instance
        mac_entries: List of dicts with keys: interface, mac, vlan

    Returns:
        Dict with stats: {"updated": int, "created": int, "errors": int}

    Raises:
        ValidationError: If MAC format invalid or interface not found

    Example:
        >>> result = process_mac_results(device, [{"mac": "00:11:22:33:44:55", ...}])
        >>> print(result)
        {'updated': 5, 'created': 2, 'errors': 0}

    """
```

**Required sections depending on context**:

- `Args`: always if the function has parameters
- `Returns`: always if the function returns something (except `None`)
- `Raises`: if exceptions can be raised
- `Example`: for important utility functions

**Modules and classes**: docstring required. Packages (`__init__.py`): optional (D104 ignored in ruff).

### 1.4 Error Handling — Recommended Patterns

**Main rule**: Never catch bare `Exception` without logging. Target the specific exception.

```python
# FORBIDDEN — exception swallowed silently
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    pass

# CORRECT — log the error, then continue
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    host.logger.warning("MAC collection subtask failed", exc_info=True)

# CORRECT — specific exception + log + raise or return
try:
    device = Device.objects.get(name=device_name)
except Device.DoesNotExist:
    self.logger.error("Device %s not found", device_name)
    return None
```

**Pattern in Jobs**: try/except per device so that a single device failure doesn't crash the entire job:

```python
for device_name, device_obj in device_map.items():
    try:
        host_result = results[device_name]
        if host_result.failed:
            stats["failed"] += 1
            continue
        if commit:
            self.process_results(device_obj, host_result.result)
            stats["success"] += 1
    except Exception as e:
        stats["failed"] += 1
        self.logger.error(
            "Failed: %s",
            e,
            extra={"grouping": device_name},
        )
```

**RuntimeError rule for Jobs**: only raise `RuntimeError` if ALL devices have failed:

```python
# BAD — 3 devices down out of 1500 = job FAILURE
if self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

# GOOD — FAILURE only if global infra outage
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)
```

**Custom exceptions**: inherit from a project base exception. Log BEFORE re-raising.

### 1.5 Logging — Format and Structured Logging

**Basic rule**: Always use `logging.getLogger(__name__)`. Never use `print()`.

```python
import logging
logger = logging.getLogger(__name__)
```

**Levels**:

- `DEBUG`: detailed flow (intermediate values, loops)
- `INFO`: normal business operations (device collected, entry created)
- `WARNING`: acceptable degradation (device unreachable out of 1500, fallback activated)
- `ERROR`: operation failure (device skipped, DB error)

**Message format**: lazy formatting `%s`/`%d` in logger calls (no f-strings):

```python
# GOOD — lazy formatting (not evaluated if level disabled)
logger.info("Device %s: interface %s updated", device.name, intf.name)
logger.error("Collection failed for %s: %s", device_name, error_msg)

# FORBIDDEN in logger.* (but OK elsewhere)
logger.info(f"Device {device.name} updated")  # f-string evaluated even if DEBUG disabled
```

**Structured logging with `extra={"grouping": ...}`** (Nautobot Jobs):

```python
# In Nautobot Jobs — group logs by device
self.logger.info(
    "Collected %d MACs",
    mac_count,
    extra={"grouping": device.name},
)
self.logger.error(
    "Collection failed: %s",
    error_msg,
    extra={"grouping": device_name},
)
self.logger.info(
    "Completed: %d success, %d failed",
    stats["success"],
    stats["failed"],
    extra={"grouping": "summary"},
)
```

**`%` vs f-string rule**: Ruff UP031 flags `%` outside logger calls. Use f-strings everywhere except in `logger.*` calls:

```python
# BAD (UP031) outside logger
summary = "Completed in %.1fs" % elapsed

# GOOD outside logger
summary = f"Completed in {elapsed:.1f}s"

# GOOD in logger (keep lazy %s)
logger.info("Completed in %.1fs", elapsed)
```

### 1.6 Naming

- `snake_case` for functions/variables/modules
- `PascalCase` for classes
- `UPPER_SNAKE_CASE` for constants
- Prefix `_` for internal unexposed functions/methods
- Explicit names: `device_queryset` rather than `qs`, `interface_count` rather than `cnt`

### 1.7 Django ORM — Rules

```python
# NEVER query inside a loop
for mac in MACAddressHistory.objects.all():
    print(mac.device.name)  # N+1 queries

# ALWAYS select_related / prefetch_related
for mac in MACAddressHistory.objects.select_related("device", "interface"):
    print(mac.device.name)  # 1 query

# .exists() rather than len() or bool()
if queryset.exists():  # GOOD
if len(queryset) > 0:  # BAD

# .count() rather than len()
count = queryset.count()  # GOOD (DB-side)
count = len(queryset)     # BAD (Python-side, loads all objects)

# Aggregate on DB side
from django.db.models.functions import TruncDate
mac_counts = dict(
    MACAddressHistory.objects.filter(first_seen__gte=start_date)
    .annotate(date=TruncDate("first_seen"))
    .values("date")
    .annotate(count=Count("id"))
    .values_list("date", "count")
)
```

### 1.8 Django Models — Standards

- Every model has an explicit and useful `__str__`
- `Meta.ordering` by default when relevant
- `Meta.constraints` and `Meta.indexes` rather than ad-hoc validation
- No business logic in models beyond `clean()` — business logic goes in dedicated services or functions
- ForeignKeys always have an explicit `related_name` and a deliberate `on_delete`
- Every nullable field justifies why `null=True` is necessary

---

## 2. Architecture Principles

Source: `CLAUDE.md`, `docs/architecture.md`

### 2.1 Fundamental Principles

The plugin strictly follows [Network-to-Code best practices](https://github.com/nautobot/cookiecutter-nautobot-app):

1. **`validated_save()` ALWAYS** — never `.save()` directly
2. **Structured Logging** — `self.logger.info(..., extra={"grouping": device.name})`
3. **Error Handling** — graceful degradation, a single device failure doesn't crash the entire job
4. **Transactions** — `transaction.atomic()` for DB operations
5. **Type Hints** — Python 3.10+ type hints throughout

### 2.2 NEVER Degrade Production Code for Test Infrastructure (CRITICAL)

**Absolute rule**: Production code follows industry standards. If a test tool (FakeNOS, mock, simulator) doesn't behave correctly, the problem is the test tool — not the production code.

Never:

- Add `if fakenos:` branches in job code
- Skip NAPALM to go directly to Netmiko because FakeNOS returns incorrect data from NAPALM getters
- Loosen validation or error handling to tolerate incorrect test data
- Any "temporary" hack that degrades the standard collection flow (NAPALM first -> Netmiko/TextFSM fallback)

The correct approach is **always** to fix the test infrastructure (FakeNOS config, mock data, simulator responses) so it behaves like real equipment.

### 2.3 Separation of Responsibilities

```text
nautobot_<plugin>/
├── __init__.py           # NautobotAppConfig — configuration only
├── models.py             # Models + validation + update_or_create_entry
├── views.py              # UI views — no business logic
├── filters.py            # FilterSets — filtering only
├── tables.py             # django-tables2 Tables — display only
├── forms.py              # Forms — user input validation
├── urls.py               # Routing only
├── navigation.py         # Menu — declarative only
├── template_content.py   # Nautobot template extensions
├── signals.py            # post_migrate handlers + purge utilities
├── admin.py              # Django admin
├── api/
│   ├── serializers.py    # DRF Serializers
│   ├── views.py          # API ViewSets
│   └── urls.py           # API Routes
└── jobs/
    ├── __init__.py       # register_jobs() — MANDATORY
    ├── _base.py          # BaseCollectionJob (abstract) + shared utilities
    ├── collect_*.py      # Specific collection jobs
    └── purge_*.py        # Purge job
```

**Responsibility rule**:

- `models.py`: source of truth for normalization functions (DRY)
- `jobs/_base.py`: shared code between jobs (avoids circular imports)
- `signals.py`: only signal handlers and programmatic purge functions
- No business logic in views, serializers, or templates

### 2.4 What Must Never Be Degraded

| Principle | Rule |
| --------- | ---- |
| `validated_save()` | Never bypassed, even in tests |
| NetDB UPDATE/INSERT logic | `update_or_create_entry()` always used, never simple `create()` |
| Error isolation per device | try/except per device in the processing loop |
| Parallel collection | Single `nr.run()` on all hosts, never a serial loop |
| Secrets via Nautobot | Never hardcoded, always via `CredentialsNautobotSecrets` |

### 2.5 Nautobot Base Class Inheritance

| Component | Parent Class | Source |
| --------- | ------------ | ------ |
| Business models | `PrimaryModel` | `nautobot.apps.models` |
| Organizational models | `OrganizationalModel` | `nautobot.apps.models` |
| UI ViewSets | `NautobotUIViewSet` | `nautobot.apps.views` |
| API ViewSets | `NautobotModelViewSet` | `nautobot.apps.views` |
| Serializers | `NautobotModelSerializer` | `nautobot.apps.api.serializers` |
| FilterSets | `NautobotFilterSet` | `nautobot.apps.filters` |
| Model Forms | `NautobotModelForm` | `nautobot.apps.forms` |
| Filter Forms | `NautobotFilterForm` | `nautobot.apps.forms` |
| Tables | `BaseTable` | `nautobot.apps.tables` |
| Template Extensions | `TemplateExtension` | `nautobot.apps.ui` |
| Jobs | `Job` | `nautobot.apps.jobs` (Nautobot 3.x) |
| App Config | `NautobotAppConfig` | `nautobot.apps` |

Never inherit directly from `django.db.models.Model` or raw DRF classes.

---

## 3. Pitfalls Nautobot 3.x — Complete and Verbatim

Source: `docs/nautobot_plugin_dev_lessons.md` — reproduced in full for reuse in the new plugin.

---

### 3.1 Nornir and Parallelism

#### golden-config Pattern (REFERENCE)

The reference pattern is from [nautobot-app-golden-config](https://github.com/nautobot/nautobot-app-golden-config/tree/v3.0.2/nautobot_golden_config/nornir_plays). Every Nornir job must follow it.

**Correct**: a single `nr.run()` on all hosts in parallel.

```python
def run(self, *, devices, workers, timeout, commit, **kwargs):
    # 1. Get target devices
    devices = self.get_target_devices(...)

    # 2. Initialize Nornir (inventory = all devices)
    nr = self.initialize_nornir(devices, workers, timeout)

    # 3. Build device_map (skip devices not in inventory)
    device_map = {}
    for device_obj in devices:
        if device_obj.name not in nr.inventory.hosts:
            self.stats["devices_skipped"] += 1
            continue
        device_map[device_obj.name] = device_obj

    # 4. Single nr.run() — Nornir handles parallelism and timeouts
    results = nr.run(task=_combined_task, **task_kwargs)

    # 5. Sequential DB writes per device
    for device_name, device_obj in device_map.items():
        host_result = results[device_name]
        if host_result.failed:
            self.stats["devices_failed"] += 1
            continue
        # process results...
```

#### Errors to NEVER Make

| Anti-pattern | Why it's bad |
| ------------ | ------------ |
| Serial reachability check loop BEFORE `nr.run()` | Defeats parallelism. One TCP check per device = N * 5s in series |
| `nr.filter(name=device_name).run()` in a loop | Same — disguised sequential execution |
| Retry logic after `nr.run()` with `time.sleep()` | Blocks the entire job. Nornir handles timeouts natively |
| `tenacity` retry decorator on `_collect_from_host()` | Unnecessary complexity. If a device fails, it fails — log and continue |
| `_collect_from_host()` per-device method | Dead code when using `_combined_*_task` with `nr.run()` |

#### Combined Task (correct pattern)

To collect multiple data types on the same host in a single SSH session:

```python
def _combined_collection_task(task, *, collect_mac=True, collect_arp=True):
    """Runs within nr.run() — one instance per host, in parallel."""
    host = task.host
    result_data = {"mac_table": [], "arp_table": []}

    if collect_mac:
        try:
            mac_sub = task.run(task=collect_mac_table_task)
            if not mac_sub.failed:
                result_data["mac_table"] = mac_sub.result or []
        except Exception:
            host.logger.warning("MAC collection subtask failed")

    if collect_arp:
        try:
            arp_sub = task.run(task=collect_arp_table_task)
            if not arp_sub.failed:
                result_data["arp_table"] = arp_sub.result or []
        except Exception:
            host.logger.warning("ARP collection subtask failed")

    return Result(host=host, result=result_data)
```

#### NornirSubTaskError: Root Cause Extraction (CRITICAL)

When `task.run()` fails (SSH timeout, connection refused, auth failure), Nornir raises `NornirSubTaskError`. The `exc.result` attribute is a **`MultiResult`** (list of `Result`), NOT a single `Result`. Accessing `exc.result.exception` never works because lists don't have an `.exception` attribute.

```python
# BAD — exc.result is a list, .exception does not exist
# Fallback to str(exc) = "Subtask: collect_mac_table_task (failed)"
except NornirSubTaskError as exc:
    root_cause = (
        exc.result.exception
        if hasattr(exc.result, "exception") and exc.result.exception
        else exc  # ← always this branch, useless generic message
    )

# GOOD — iterate the MultiResult to find the failed Result
def _extract_nornir_error(exc: NornirSubTaskError) -> str:
    """Extract root cause from NornirSubTaskError.

    NornirSubTaskError.result is a MultiResult (list of Result objects).
    Iterate to find the actual failed Result's exception or error message.
    """
    if hasattr(exc, "result"):
        for r in exc.result:
            if r.failed:
                if r.exception:
                    return str(r.exception)
                if r.result:
                    return str(r.result)
    return str(exc)

# Usage
except NornirSubTaskError as exc:
    root_cause = _extract_nornir_error(exc)
    # → "TCP connection to device failed. Common causes: ..."
```

#### Partial Job: don't raise RuntimeError on devices_failed > 0

A collection job on 1500 devices will inevitably have some failures (maintenance, outage, ACL). Marking the entire job as FAILURE prevents monitoring from distinguishing a real problem from normal operation.

```python
# BAD — 3 devices down out of 1500 = job FAILURE + RuntimeError in Celery
if self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

# GOOD — FAILURE only if NO device succeeded (global infra outage)
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

return {
    "success": self.stats["devices_failed"] == 0,  # True si 100% success
    "summary": summary_msg,
    **self.stats,
}
```

| Scenario | Before | After |
| -------- | ------ | ----- |
| 1500/1500 OK | SUCCESS | SUCCESS |
| 1497/1500 OK, 3 down | FAILURE + RuntimeError | SUCCESS (success=False in result) |
| 0/1500 OK (infra outage) | FAILURE + RuntimeError | FAILURE + RuntimeError |

#### Mocking Nornir in Tests

Always mock `nr.run()` directly, never `nr.filter().run()` or `_collect_from_host`:

```python
@patch("nautobot_netdb_tracking.jobs._base.InitNornir")
@patch("nautobot_netdb_tracking.jobs._base.NautobotORMInventory", None)
def test_job_commit_mode(self, mock_init_nornir, device_with_platform, interface):
    mock_nr = MagicMock()
    mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}
    mock_init_nornir.return_value = mock_nr

    # Mock nr.run() — NOT nr.filter().run()
    mock_host_result = MagicMock()
    mock_host_result.failed = False
    mock_host_result.result = {"mac_table": [...], "arp_table": [...]}
    mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

    job = CollectMACARPJob()
    job.logger = MagicMock()
    result = job.run(...)
```

---

### 3.2 NautobotORMInventory and NAPALM

#### Problem: network_driver != napalm_driver

`NautobotORMInventory` uses `Platform.network_driver` (e.g., `arista_eos`) for `host.platform`. But NAPALM expects `Platform.napalm_driver` (e.g., `eos`). Without correction, NAPALM fails to find the correct driver.

#### Problem: host-level extras overwrite defaults

Extras configured per host in `NautobotORMInventory` (via config context) **replace** the defaults passed to InitNornir, instead of merging them. This loses `transport`, `timeout`, etc.

#### Solution: post-init injection

After `InitNornir()`, loop over hosts to:

1. Set `napalm_opts.platform` from `Platform.napalm_driver`
2. Merge `Platform.napalm_args` into `napalm_opts.extras.optional_args`

```python
# Build maps BEFORE InitNornir
napalm_driver_map = {}
napalm_args_map = {}
for d in devices.select_related("platform"):
    if d.platform and d.platform.napalm_driver:
        napalm_driver_map[d.name] = d.platform.napalm_driver
    if d.platform and d.platform.napalm_args:
        napalm_args_map[d.name] = d.platform.napalm_args

nr = InitNornir(...)

# Fix AFTER InitNornir
for host_name, host in nr.inventory.hosts.items():
    napalm_driver = napalm_driver_map.get(host_name)
    napalm_opts = host.connection_options.get("napalm")
    if napalm_opts and napalm_driver:
        napalm_opts.platform = napalm_driver
    plat_args = napalm_args_map.get(host_name, {})
    if plat_args and napalm_opts:
        opt_args = napalm_opts.extras.setdefault("optional_args", {})
        for key, value in plat_args.items():
            if key not in opt_args:
                opt_args[key] = value
```

#### Config context for SSH port

The custom SSH port must be in the device's config context, under the key `nautobot_plugin_nornir.connection_options`:

```json
{
  "nautobot_plugin_nornir": {
    "connection_options": {
      "netmiko": {"extras": {"port": 6001}},
      "napalm": {"extras": {"optional_args": {"port": 6001}}}
    }
  }
}
```

Requires `use_config_context.connection_options: True` in `PLUGINS_CONFIG["nautobot_plugin_nornir"]`.

---

### 3.3 Nautobot 3.x — Models and ORM

#### IPAddress: fields renamed since Nautobot 2.x

| Nautobot 2.x | Nautobot 3.x | Notes |
| ------------ | ------------ | ----- |
| `address="10.0.0.1/24"` | `host="10.0.0.1"` + `mask_length=24` | Split into two fields |
| `namespace=ns` | `parent=prefix` | Namespace is carried by the Prefix |

Common errors:

- `FieldError: Invalid field name(s) for model IPAddress: 'namespace'` -> use `parent=prefix`
- `FieldError: ... 'address'` -> use `host` + `mask_length`

Correct creation in Nautobot 3.x:

```python
prefix = Prefix.objects.get(prefix="172.28.0.0/24")
ip = IPAddress(host="172.28.0.10", mask_length=24, status=active, parent=prefix, type="host")
ip.validated_save()
```

#### Job.grouping overwritten by validated_save()

The `grouping` field of a Job is overwritten by `validated_save()`. Use `QuerySet.update()`:

```python
Job.objects.filter(module_name__startswith="nautobot_netdb_tracking").update(
    enabled=True, grouping="NetDB Tracking"
)
```

#### validated_save() ALWAYS

Never `.save()` or `objects.create()`. Always `instance.validated_save()` or the custom `update_or_create_entry` pattern.

#### select_related / prefetch_related

Never query inside a loop. Pre-fetch:

```python
# BAD — N+1 queries
for mac in MACAddressHistory.objects.all():
    print(mac.device.name)

# GOOD — 1 query
for mac in MACAddressHistory.objects.select_related("device", "interface"):
    print(mac.device.name)
```

#### Cable: Status required in Nautobot 3.x

In Nautobot 3.x, the Cable model **requires** a Status. Without it, `validated_save()` raises a `ValidationError`. Always retrieve the "Connected" Status before creating a Cable:

```python
# BAD — ValidationError: Status is required
cable = Cable(
    termination_a=interface_a,
    termination_b=interface_b,
)
cable.validated_save()

# GOOD
from nautobot.extras.models import Status

cable_status = Status.objects.get_for_model(Cable).get(name="Connected")
cable = Cable(
    termination_a=interface_a,
    termination_b=interface_b,
    status=cable_status,
)
cable.validated_save()
```

#### UniqueConstraint: naming convention

`UniqueConstraint` names must use the `%(app_label)s_%(class)s_` prefix to avoid collisions between plugins:

```python
# BAD — risk of collision with other plugins
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["device", "interface", "mac_address", "vlan"],
            name="unique_mac_entry"
        )
    ]

# GOOD — unique prefix per app/model
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["device", "interface", "mac_address", "vlan"],
            name="%(app_label)s_%(class)s_unique_mac_entry"
        )
    ]
```

#### natural_key_field_lookups for models

Nautobot 3.x models must define `natural_key_field_lookups` in their Meta for natural key support in the API and filters. Without it, natural key lookups fail silently:

```python
class MACAddressHistory(PrimaryModel):
    class Meta:
        natural_key_field_lookups = {
            "device__name": "device",
            "interface__name": "interface",
            "mac_address": "mac_address",
        }
```

#### Race condition: count() then delete()

The `count()` followed by `delete()` pattern is non-atomic. Another process can modify the data between the two calls. Use the return value of `delete()`:

```python
# BAD — race condition, the count may not match the delete
count = queryset.filter(last_seen__lt=cutoff).count()
queryset.filter(last_seen__lt=cutoff).delete()
stats["deleted"] = count

# GOOD — atomic, no race window
deleted_count, _ = queryset.filter(last_seen__lt=cutoff).delete()
stats["deleted"] = deleted_count
```

---

### 3.4 Nautobot 3.x — Jobs

#### Job Registration (MANDATORY)

`jobs/__init__.py` MUST call `register_jobs()`. Without it, jobs are importable but don't appear in the UI:

```python
from nautobot.core.celery import register_jobs
from myapp.jobs.my_job import MyJob

jobs = [MyJob]
register_jobs(*jobs)
```

#### ScriptVariable: attribute access

Defaults and constraints are in `field_attrs`, not as direct attributes:

```python
# BAD
job.retention_days.default  # AttributeError
job.retention_days.min_value  # AttributeError

# GOOD
job.retention_days.field_attrs["initial"]  # 90
job.retention_days.field_attrs["min_value"]  # 1
job.commit.field_attrs["initial"]  # True
```

#### Plugin registration in tests

`test_settings.py` needs BOTH:

```python
PLUGINS = ["nautobot_netdb_tracking"]           # for nautobot-server (CI)
INSTALLED_APPS.append("nautobot_netdb_tracking")  # for pytest-django
```

`django.setup()` does NOT process `PLUGINS`. `nautobot-server` does NOT read `DJANGO_SETTINGS_MODULE`.

#### CI: migrations

Use `nautobot-server init` then add the plugin, not `django-admin`:

```yaml
- name: Initialize Nautobot configuration
  run: |
    poetry run nautobot-server init
    echo 'PLUGINS = ["nautobot_netdb_tracking"]' >> ~/.nautobot/nautobot_config.py
- name: Run migrations
  run: poetry run nautobot-server makemigrations nautobot_netdb_tracking
```

`django-admin` does not process `PLUGINS`. `nautobot-server` does not read `DJANGO_SETTINGS_MODULE`.

---

### 3.5 Nautobot 3.x — API and Serializers

#### select_related in API ViewSets

`NautobotModelViewSet` must include **all** FK fields used by the serializer in `select_related()`. Otherwise, each serialized object generates additional queries (N+1):

```python
# BAD — ip_address_object is in the serializer but not in select_related
class ARPEntryViewSet(NautobotModelViewSet):
    queryset = ARPEntry.objects.select_related(
        "device", "device__location", "interface",
    ).prefetch_related("tags")

# GOOD — all FK fields from the serializer are pre-loaded
class ARPEntryViewSet(NautobotModelViewSet):
    queryset = ARPEntry.objects.select_related(
        "device", "device__location", "interface", "ip_address_object",
    ).prefetch_related("tags")
```

**Rule**: for each FK field in the serializer's `fields`, verify it is in `select_related()` of the corresponding ViewSet (UI and API).

#### Nested serializers: don't create dead code

Don't declare "nested" or "lite" serializers in anticipation. An unimported serializer is dead code:

```python
# BAD — serializer declared but never used
class MACAddressHistoryNestedSerializer(NautobotModelSerializer):
    class Meta:
        model = MACAddressHistory
        fields = ["id", "url", "display", "mac_address", "last_seen"]

# GOOD — only create what is actually used
# If a nested serializer becomes necessary, create it at that time
```

---

### 3.6 Nautobot 3.x — Tests

#### FilterSet: input format (CRITICAL)

| Filter type | Expected format | Example |
| ----------- | --------------- | ------- |
| `NaturalKeyOrPKMultipleChoiceFilter` (FK) | List of strings | `{"device": [str(device.pk)]}` |
| `CharFilter` | Simple string | `{"mac_address": "00:11:22"}` |

```python
# BAD — bare value for FK filters
filterset = MACAddressHistoryFilterSet({"device": device.pk})
filterset = MACAddressHistoryFilterSet({"device": device.name})

# GOOD — wrap FK/PK values in a list of strings
filterset = MACAddressHistoryFilterSet({"device": [str(device.pk)]})
filterset = MACAddressHistoryFilterSet({"device": [device.name]})

# GOOD — CharFilter uses simple strings (not a list)
filterset = MACAddressHistoryFilterSet({"mac_address": "00:11:22"})
filterset = MACAddressHistoryFilterSet({"q": "search term"})
```

#### NaturalKeyOrPKMultipleChoiceFilter: to_field_name

`NaturalKeyOrPKMultipleChoiceFilter` uses `to_field_name="name"` by default. But some Nautobot models don't have a `name` field — for example `IPAddress` which uses `host`:

```python
# BAD — FieldError: Cannot resolve keyword 'name' into field
ip_address_object = NaturalKeyOrPKMultipleChoiceFilter(
    queryset=IPAddress.objects.all(),
    label="IPAM IP Address",
)

# GOOD — specify the correct lookup field
ip_address_object = NaturalKeyOrPKMultipleChoiceFilter(
    queryset=IPAddress.objects.all(),
    to_field_name="host",
    label="IPAM IP Address",
)
```

**Rule**: always verify that the target model has a `name` field. Otherwise, specify `to_field_name` explicitly.

#### BaseTable: no configure()

Nautobot `BaseTable` does NOT have a `configure(request)` method. Never call it:

```python
# BAD — AttributeError
table = MACAddressHistoryTable(data)
table.configure(request)

# GOOD
table = MACAddressHistoryTable(data)
```

Null FK cells can render as `&mdash;` (HTML entity), not just `—` or `""`:

```python
# BAD — strict string match for null cells
assert str(cell) in ["", "—", "-"]

# GOOD — account for HTML entity rendering
assert cell is None or "—" in str(cell) or "&mdash;" in str(cell) or str(cell) in ["", "-"]
```

#### Tab view templates: render_table and obj_table.html

`{% render_table table %}` without a template argument uses Nautobot's `DJANGO_TABLES2_TEMPLATE` (`utilities/obj_table.html`). This template accesses `table.context` which only exists if the table was configured via `RequestConfig`. Tab views create tables without `RequestConfig` -> crash `AttributeError: object has no attribute 'context'`.

```django
{# BAD — crashes on tab views #}
{% render_table table %}

{# GOOD — force a simple template that does not require table.context #}
{% render_table table "django_tables2/bootstrap5.html" %}
```

#### test_settings.py: CACHES must include TIMEOUT

```python
# BAD
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://localhost:6379/0",
    }
}

# GOOD
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://localhost:6379/0",
        "TIMEOUT": 300,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}
```

#### Nautobot 3.x export: ExportTemplate required

Nautobot 3.x uses `ExportTemplate` objects for CSV/YAML export. Without a configured `ExportTemplate`, a `?export=csv` request returns **404** (not an empty CSV or a 500 error):

```python
# GOOD — test that export without template returns 404
def test_export_without_template(self, authenticated_client):
    url = reverse("plugins:myapp:mymodel_list")
    response = authenticated_client.get(url, {"export": "csv"})
    assert response.status_code == 404
```

#### API test URLs: reverse() vs hardcoded paths

`reverse()` with nested namespaces is fragile in test environments. Reliable solution: use hardcoded URL paths in API tests:

```python
# BAD — NoReverseMatch if the namespace is not correctly injected
url = reverse("plugins-api:nautobot_netdb_tracking-api:macaddresshistory-list")

# GOOD — reliable, no dependency on the resolver
_API_BASE = "/api/plugins/netdb-tracking"

def _mac_list_url():
    return f"{_API_BASE}/mac-address-history/"

def _mac_detail_url(pk):
    return f"{_API_BASE}/mac-address-history/{pk}/"
```

#### conftest.py: use validated_save()

Test fixtures must use `validated_save()`, not `.create()` or `.save()`:

```python
# BAD — bypasses model validations
@pytest.fixture
def mac_entry(device, interface):
    return MACAddressHistory.objects.create(
        device=device, interface=interface, mac_address="AA:BB:CC:DD:EE:FF",
        last_seen=timezone.now()
    )

# GOOD — validates constraints and clean()
@pytest.fixture
def mac_entry(device, interface):
    entry = MACAddressHistory(
        device=device, interface=interface, mac_address="AA:BB:CC:DD:EE:FF",
        last_seen=timezone.now()
    )
    entry.validated_save()
    return entry
```

#### Test coverage: commonly missed areas

| Area to test | Why |
| ------------ | --- |
| Forms (`NautobotModelForm`, `NautobotFilterForm`) | Validate `query_params`, `required`, widgets, and the `clean()` method |
| TemplateExtension (`template_content.py`) | Verify HTML rendering, contexts, and N+1 queries in panels |
| Permissions on custom views | Verify that non-NautobotUIViewSet views return 403/302 for anonymous users |
| Active CI test job | The test job in `.github/workflows/ci.yml` must never be commented out |

#### Permission tests on views

```python
def test_dashboard_requires_login(client):
    """Verify anonymous users are redirected to login."""
    response = client.get("/plugins/netdb-tracking/dashboard/")
    assert response.status_code == 302
    assert "/login/" in response.url

def test_dashboard_requires_permission(authenticated_client):
    """Verify permission check is enforced."""
    response = authenticated_client.get("/plugins/netdb-tracking/dashboard/")
    assert response.status_code == 403
```

---

### 3.7 Django — Views and Templates

#### Authentication Mixins

Custom views (non-NautobotUIViewSet) MUST have auth mixins:

```python
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin

class NetDBDashboardView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_macaddresshistory"
```

`NautobotUIViewSet` handles auth automatically. Standard Django `View` classes do NOT.

**Watch out for tab views**: each `permission_required` must match the model displayed by the view, not a generic permission common to all views:

```python
# BAD — accessible without authentication
class DeviceMACTabView(View):
    def get(self, request, pk): ...

# GOOD — auth + model-specific permissions
class DeviceMACTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_macaddresshistory"

class DeviceARPTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_arpentry"

class DeviceTopologyTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_topologyconnection"
```

#### QueryDict.pop() vs getlist()

`QueryDict.pop(key)` returns the **last value** (a single string), not a list. For multi-value parameters, use `request.GET.getlist()`:

```python
# BAD — returns "uuid2" (string), not ["uuid1", "uuid2"]
devices = request.GET.pop("device", None)

# GOOD — returns ["uuid1", "uuid2"]
devices = request.GET.getlist("device")
```

#### Template tags

External Django filters require an explicit `{% load %}`:

```django
{# BAD — TemplateSyntaxError #}
{% load helpers %}
{{ value|intcomma }}

{# GOOD #}
{% load helpers humanize %}
{{ value|intcomma }}
```

#### Nautobot UI Template Standards (CRITICAL)

All plugin templates MUST follow native Nautobot patterns.

**Table rendering** — ALWAYS use `inc/table.html` (NautobotUIViewSet views):

```django
{# BAD — django_tables2 default template, wrong pagination style #}
{% render_table table "django_tables2/bootstrap5.html" %}

{# GOOD — standard Nautobot template, used by all core views #}
{% render_table table "inc/table.html" %}
```

**Pagination** — ALWAYS use `inc/paginator.html` with `EnhancedPaginator`:

```python
# BAD — default Django paginator
RequestConfig(request, paginate={"per_page": 50}).configure(table)

# GOOD — Nautobot EnhancedPaginator
from nautobot.core.views.paginator import EnhancedPaginator, get_paginate_count

per_page = get_paginate_count(request)
RequestConfig(
    request,
    paginate={"per_page": per_page, "paginator_class": EnhancedPaginator},
).configure(table)
```

```django
{# In the template, after the table card #}
{% include 'inc/paginator.html' with paginator=table.paginator page=table.page %}
```

**Page titles** — NEVER create a duplicate `<h1>`:

```django
{# BAD — base_django.html already renders {% block title %} as <h1> #}
{% block title %}My Page{% endblock %}
{% block content %}
<h1>My Page</h1>  {# DUPLICATE — creates two <h1> on the page #}
{% endblock %}

{# GOOD — let Nautobot handle the <h1> via {% block title %} only #}
{% block title %}My Page{% endblock %}
{% block content %}
{# No <h1> here #}
{% endblock %}
```

**Breadcrumbs** — only on detail pages (level 2):

```django
{# BAD — breadcrumbs on list/report pages #}
{% block breadcrumbs %}
<li class="breadcrumb-item"><a href="...">Parent</a></li>
<li class="breadcrumb-item active">Current Page</li>
{% endblock %}

{# GOOD — empty breadcrumbs on list/report pages #}
{% block breadcrumbs %}{% endblock %}
```

**`{% load %}` syntax** — separate lines for different libraries:

```django
{# BAD — Django parses "from" and loads helpers/humanize from django_tables2 #}
{% load helpers humanize render_table from django_tables2 %}

{# GOOD — separate load statements #}
{% load helpers humanize %}
{% load render_table from django_tables2 %}
```

---

### 3.8 Custom Views with Filter Sidebar and Pagination

When creating a custom page (not a `NautobotUIViewSet`) but wanting native Nautobot look, there are 5 major pitfalls:

#### Pitfall 1: `generic/object_list.html` is coupled to NautobotUIViewSet

Do NOT extend `generic/object_list.html` for a custom view. This template is tightly coupled to the context provided by `NautobotHTMLRenderer`. **Solution**: extend `base.html`.

#### Pitfall 2: `BaseTable` requires a `Meta.model`

`BaseTable.__init__` calls `CustomField.objects.get_for_model(model)`. If `Meta.model` is `None` (dict-based table), it crashes.

**Solution**: use `django_tables2.Table` instead of `BaseTable`:

```python
import django_tables2 as tables

class MyCustomTable(tables.Table):  # NOT BaseTable!
    col1 = tables.Column()

    class Meta:
        template_name = "django_tables2/bootstrap5.html"  # MANDATORY
        attrs = {"class": "table table-hover nb-table-headings"}
        fields = ("col1",)
```

#### Pitfall 3: the default django-tables2 template is a custom Nautobot template

`DJANGO_TABLES2_TEMPLATE` is set to `utilities/obj_table.html` in Nautobot. This template accesses `table.data.verbose_name_plural`, `permissions.change`, etc. — all of which are absent for a `tables.Table` with dicts.

**Solution**: force `template_name = "django_tables2/bootstrap5.html"` in `Meta`.

#### Pitfall 4: `{% filter_form_drawer %}` has 4 required positional args

```django
{# BAD — TemplateSyntaxError: did not receive value(s) for 'filter_params' #}
{% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title %}

{# GOOD #}
{% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title filter_params=filter_params %}
```

The view MUST pass `dynamic_filter_form` (= `None`) and `filter_params` (= `[]`) in the context.

#### Pitfall 5: `{% load X Y Z from library %}` loads X, Y, Z from library

```django
{# BAD — Django looks for "helpers" and "humanize" in django_tables2 #}
{% load helpers humanize render_table from django_tables2 %}

{# GOOD — load separately #}
{% load helpers humanize %}
{% load render_table from django_tables2 %}
```

#### Complete Pattern — View

```python
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.generic import View
from django_tables2 import RequestConfig

from myapp.forms import MyFilterForm
from myapp.tables import MyCustomTable

class MyCustomView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "myapp.view_mymodel"
    template_name = "myapp/my_page.html"

    def get(self, request: HttpRequest) -> HttpResponse:
        filter_form = MyFilterForm(request.GET or None)
        all_data = [{"col1": "a", "col2": "b"}, ...]
        table = MyCustomTable(all_data)
        per_page = request.GET.get("per_page", 50)
        RequestConfig(request, paginate={"per_page": per_page}).configure(table)

        return render(request, self.template_name, {
            "table": table,
            "filter_form": filter_form,
            "dynamic_filter_form": None,   # required by filter_form_drawer
            "filter_params": [],            # required by filter_form_drawer
            "title": "My Page",
            "permissions": {"add": False, "change": False, "delete": False, "view": True},
            "action_buttons": (),
            "content_type": None,
        })
```

#### Quick Checklist

| Element | How |
| ------- | --- |
| Table class | `tables.Table` (NOT `BaseTable`) |
| `Meta.template_name` | `"django_tables2/bootstrap5.html"` |
| `Meta.attrs` | `{"class": "table table-hover nb-table-headings"}` |
| Form class | `NautobotFilterForm` with `model = Device` |
| Template extends | `base.html` (NOT `generic/object_list.html`) |
| `{% load %}` | Separate native loads and `from library` |
| Drawer block | `{% filter_form_drawer %}` with 4 args |
| View context | `dynamic_filter_form=None`, `filter_params=[]` |
| Pagination | `RequestConfig(request, paginate={"per_page": 50}).configure(table)` |
| Filter button | `data-nb-toggle="drawer" data-nb-target="#FilterForm_drawer"` |

---

### 3.9 Django — Signals

#### post_migrate: always specify sender

A `post_migrate` signal without `sender` executes for **every** Django app that migrates (40+ apps in Nautobot). Specify the sender to only execute it for our app:

```python
# BAD — runs 40+ times on each migrate
post_migrate.connect(enable_netdb_jobs)

# GOOD — runs only once for our app
from django.apps import apps

post_migrate.connect(
    enable_netdb_jobs,
    sender=apps.get_app_config("nautobot_netdb_tracking"),
)
```

#### Signal receiver: handle idempotency

The `post_migrate` handler can execute multiple times. Always write idempotent handlers:

```python
def enable_netdb_jobs(sender, **kwargs):
    """Enable jobs after migration — idempotent."""
    from nautobot.extras.models import Job

    Job.objects.filter(
        module_name__startswith="nautobot_netdb_tracking",
        enabled=False,  # Only touch jobs not yet active
    ).update(enabled=True, grouping="NetDB Tracking")
```

---

### 3.10 Python — Code Quality

#### Single normalization function (DRY)

Never duplicate a normalization function across multiple modules. Define **one single source of truth** in the lowest module in the hierarchy (typically `models.py`) and import everywhere:

```python
# BAD — two nearly identical functions in two modules
# models.py : normalize_mac_address() → UPPERCASE
# jobs/collect_mac_arp.py : normalize_mac() → lowercase

# GOOD — a single canonical function in models.py
# models.py
def normalize_mac_address(mac: str) -> str:
    """Normalize MAC to XX:XX:XX:XX:XX:XX."""
    ...

# jobs/collect_mac_arp.py — import from models
from nautobot_netdb_tracking.models import normalize_mac_address
```

#### Circular imports between job modules

Avoid direct imports between job modules. Extract shared functions into `_base.py` or `utils.py`:

```python
# BAD — potential circular import
from nautobot_netdb_tracking.jobs.collect_topology import normalize_interface_name

# GOOD — shared function in _base.py
from nautobot_netdb_tracking.jobs._base import normalize_interface_name
```

#### Exception handling: never bare `except Exception: pass`

```python
# BAD — exception swallowed silently
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    pass

# GOOD — log the error, then continue
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    host.logger.warning("MAC collection subtask failed", exc_info=True)
```

---

### 3.11 Nautobot Status — Semantic Pitfalls

#### Never use a semantically incorrect status as fallback

The default statuses for `dcim.interface` are: **Active, Decommissioning, Failed, Maintenance, Planned**. None corresponds to "interface operationally down".

```python
# FORBIDDEN — "Planned" means "not yet deployed", not "oper-down"
status_inactive = interface_statuses.filter(name="Planned").first()
status_inactive_obj = interface_statuses.filter(name="Inactive").first()
if status_inactive_obj:
    status_inactive = status_inactive_obj
# If "Inactive" does not exist → fallback to "Planned" → BUG

# GOOD — if the status does not exist, do not change
status_down = interface_statuses.filter(name="Down").first()
# status_down can be None → the condition short-circuits → no change
if not is_up and status_down and nb_interface.status == status_active:
    nb_interface.status = status_down
```

#### The "Down" status exists but not for interfaces

The "Down" status is pre-installed in Nautobot but only for `ipam.vrf` and `vpn.vpntunnel`. To use it on interfaces, add the content type via the API or a `post_migrate` signal.

---

### 3.12 Docker — Hot Deployment of the Plugin

#### Correct Sequence (CRITICAL)

`pip install --upgrade` is a **no-op** if the version hasn't changed. The Celery worker keeps the old code in memory even after `pip install`.

```bash
# BAD — does not reinstall if same version, old /tmp/ stale
docker cp ./plugin container:/tmp/plugin
docker exec container pip install --upgrade /tmp/plugin
docker restart container

# GOOD — rm, cp fresh, force-reinstall, restart, verify
for c in nautobot nautobot-worker nautobot-scheduler; do
  docker exec $c rm -rf /tmp/nautobot_netdb_tracking
  docker cp ./nautobot_netdb_tracking $c:/tmp/nautobot_netdb_tracking
  docker exec $c pip install --force-reinstall --no-deps /tmp/nautobot_netdb_tracking
done
docker restart nautobot nautobot-worker nautobot-scheduler
```

**Why `--force-reinstall --no-deps`**:

- `--force-reinstall`: forces pip to reinstall even if the version is identical
- `--no-deps`: avoids reinstalling all dependencies (much faster)

---

### 3.13 FakeNOS and Integration Tests

#### Critical Limitation

NAPALM getters "succeed" on FakeNOS but return **inconsistent data** (wrong MACs, wrong interfaces, VLAN 666). The Netmiko/TextFSM fallback never triggers because NAPALM doesn't raise an exception.

#### Absolute Rule

**NEVER** modify production code to work around FakeNOS limitations. Fix the test infrastructure instead.

#### TextFSM: destination_port is a list

The `destination_port` field from the TextFSM Cisco IOS MAC table template returns a **list** (`['Gi1/0/1']`), not a string:

```python
interface = entry.get("destination_port") or entry.get("interface") or ""
if isinstance(interface, list):
    interface = interface[0] if interface else ""
```

---

### 3.14 Configuration and Packaging

#### Dead dependencies in pyproject.toml

Remove any dependency that is no longer imported in the code. Verify with:

```bash
rg 'import tenacity|from tenacity' nautobot_netdb_tracking/
rg 'import macaddress|from macaddress' nautobot_netdb_tracking/
```

#### Black + Ruff: a single formatter

Configuring both Black **and** Ruff creates potential conflicts. Choose a single tool. Ruff is the current standard (faster, includes formatting + linting):

```toml
# GOOD — ruff only
[tool.ruff]
line-length = 120
```

#### CI: never comment out the test job

The test job in `.github/workflows/ci.yml` must **never** be commented out. CI without tests is a false sense of security.

---

### 3.15 Pre-commit Checklist (complete)

#### Linting and Formatting

1. `ruff check` — zero new errors
2. `ruff format --check` — zero new files to reformat

#### Models and ORM

1. No `.save()` — always `validated_save()`
2. No queries inside a loop — `select_related` / `prefetch_related`
3. Every `Cable()` has a `status=` (retrieved via `Status.objects.get_for_model(Cable)`)
4. `UniqueConstraint` names use the `%(app_label)s_%(class)s_` prefix
5. No separate `count()` + `delete()` — use the return value of `delete()`

#### Views and API

1. Custom views (`View`) have `LoginRequiredMixin` + `PermissionRequiredMixin`
2. Each `permission_required` matches the displayed model (not a generic permission)
3. API ViewSets have all serializer FK fields in `select_related()`
4. No dead serializer/code — remove anything that isn't imported

#### Jobs and Signals

1. `post_migrate.connect()` has a `sender=` to avoid multiple executions
2. No unnecessary dependencies in `pyproject.toml` — verify imports

#### Tests

1. Fixtures use `validated_save()`, not `.create()` or `.save()`
2. FK filter tests use lists: `[str(device.pk)]`
3. No `.configure(request)` on tables
4. The CI test job is NOT commented out

#### Nornir

1. `NornirSubTaskError.result` is a `MultiResult` (list) — iterate to extract the root cause
2. Don't raise `RuntimeError` on partial failure — only if `devices_success == 0`

#### Python

1. Single normalization function per concept (DRY) — source of truth in `models.py`
2. No circular imports between job modules — share via `_base.py` or `utils.py`
3. No bare `except Exception: pass` — always log before continuing
4. No `%` formatting in strings (outside `logger.*`) — use f-strings

#### Status and Transitions

1. Never use a semantically incorrect status as fallback
2. If a target status doesn't exist, **skip the transition** (`None` -> condition short-circuits)
3. Verify the status exists for the correct content type (`dcim.interface`, not just `ipam.vrf`)

#### Docker Deployment

1. `pip install --upgrade` doesn't reinstall if same version — use `--force-reinstall --no-deps`
2. Always `rm -rf /tmp/old` before `docker cp` fresh
3. Always verify installed code with `grep` after deploy

---

## 4. Testing Patterns

Sources: `tests/conftest.py`, `tests/factories.py`, `tests/test_models.py`, `tests/test_filters.py`, `CLAUDE.md`, `SPECS.md`

### 4.1 Framework: pytest

**Rule**: pytest as runner. No `unittest.TestCase` unless required by the framework. Test classes use the `Test*` convention and don't inherit.

```python
# Format standard
@pytest.mark.django_db
class TestMACAddressHistory:
    """Tests for MACAddressHistory model."""

    def test_create_basic(self, device, interface):
        """Test creating a basic MAC address history entry."""
        mac = MACAddressHistory(...)
        mac.validated_save()
        assert mac.pk is not None
```

**Test naming**: `test_<function>_<scenario>_<expected_result>`.

**Markers**:

- `@pytest.mark.django_db` for all tests that touch the DB
- `@pytest.mark.integration` for network tests (configured in `conftest.py`)
- `@pytest.mark.slow` for slow tests

### 4.2 Fixtures — All Those Defined in conftest.py

File: `/Users/thomas/AzQore/nautobot_netdb_tracking/tests/conftest.py`

#### Base Nautobot Fixtures

| Fixture | Dependencies | Returns | Notes |
| ------- | ------------ | ------- | ----- |
| `location_type` | `db` | `LocationType` | "Site", nestable=True, VLAN content type added |
| `location` | `db`, `location_type` | `Location` | "Test Site", status=first available status |
| `manufacturer` | `db` | `Manufacturer` | "Test Manufacturer" |
| `device_type` | `db`, `manufacturer` | `DeviceType` | "Test Device Type" |
| `device_role` | `db` | `Role` | "Test Role" |
| `device` | `db`, `location`, `device_type`, `device_role` | `Device` | "test-device-01" |
| `device2` | `db`, `location`, `device_type`, `device_role` | `Device` | "test-device-02" (for topology) |
| `interface` | `db`, `device` | `Interface` | "GigabitEthernet0/1", type="1000base-t" |
| `interface2` | `db`, `device2` | `Interface` | "GigabitEthernet0/1" on device2 |
| `vlan` | `db`, `location` | `VLAN` | vid=100, "Test VLAN", locations.add(location) |

#### IPAM Fixtures

| Fixture | Dependencies | Returns | Notes |
| ------- | ------------ | ------- | ----- |
| `namespace` | `db` | `Namespace` | "Test Namespace" |
| `prefix` | `db`, `namespace` | `Prefix` | "192.168.1.0/24" |
| `ip_address` | `db`, `namespace`, `prefix` | `IPAddress` | host="192.168.1.50", mask_length=24, parent=prefix, status="Active" |

#### User and Client Fixtures

| Fixture | Dependencies | Returns | Notes |
| ------- | ------------ | ------- | ----- |
| `admin_user` | `db` | `User` | superuser username="admin" |
| `regular_user` | `db` | `User` | non-admin username="regular" |
| `api_client` | `db`, `admin_user` | `APIClient` | DRF APIClient, force_authenticate |
| `authenticated_client` | `db`, `admin_user` | `Client` | Django Client, force_login |
| `client` | `db` | `Client` | unauthenticated Django Client |
| `request_factory` | — | `RequestFactory` | For table and view tests |

#### NetDB Model Fixtures

| Fixture | Dependencies | Returns | Notes |
| ------- | ------------ | ------- | ----- |
| `mac_entry` | `db`, `device`, `interface` | `MACAddressHistory` | mac="00:11:22:33:44:55", uses `.objects.create()` |
| `arp_entry` | `db`, `device`, `interface` | `ARPEntry` | ip="192.168.1.100", mac="00:11:22:33:44:55" |
| `topology_connection` | `db`, `device`, `interface`, `device2`, `interface2` | `TopologyConnection` | protocol=LLDP |

#### Fixtures Platform

| Fixture | Dependencies | Returns | Notes |
| ------- | ------------ | ------- | ----- |
| `platform_cisco_ios` | `db` | `Platform` | network_driver="cisco_ios" |
| `platform_arista_eos` | `db` | `Platform` | network_driver="arista_eos" |
| `device_with_platform` | `db`, `device`, `platform_cisco_ios` | `Device` | device with platform assigned (uses `.save()`) |

#### Additional VLAN Fixtures

| Fixture | Dependencies | Returns | Notes |
| ------- | ------------ | ------- | ----- |
| `vlan_10` | `db`, `location` | `VLAN` | vid=10, "VLAN-10" |
| `vlan_20` | `db`, `location` | `VLAN` | vid=20, "VLAN-20" |
| `vlan_30` | `db`, `location` | `VLAN` | vid=30, "VLAN-30" |

**Note**: `pytest_configure` adds the `integration` and `slow` markers.

### 4.3 Factory Boy — All Defined Factories

File: `/Users/thomas/AzQore/nautobot_netdb_tracking/tests/factories.py`

All inherit from `factory.django.DjangoModelFactory`.

#### LocationTypeFactory

```python
class LocationTypeFactory(DjangoModelFactory):
    class Meta:
        model = LocationType
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Location Type {n}")
    nestable = True

    @factory.post_generation
    def setup_content_types(self, create, extracted, **kwargs):
        if create:
            vlan_ct = ContentType.objects.get_for_model(VLAN)
            self.content_types.add(vlan_ct)
```

#### LocationFactory

```python
class LocationFactory(DjangoModelFactory):
    class Meta:
        model = Location
        django_get_or_create = ("name", "location_type")

    name = factory.Sequence(lambda n: f"Location {n}")
    location_type = factory.SubFactory(LocationTypeFactory)

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Location).first()
```

#### ManufacturerFactory

```python
class ManufacturerFactory(DjangoModelFactory):
    class Meta:
        model = Manufacturer
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Manufacturer {n}")
```

#### DeviceTypeFactory

```python
class DeviceTypeFactory(DjangoModelFactory):
    class Meta:
        model = DeviceType
        django_get_or_create = ("model", "manufacturer")

    model = factory.Sequence(lambda n: f"Device Type {n}")
    manufacturer = factory.SubFactory(ManufacturerFactory)
```

#### RoleFactory

```python
class RoleFactory(DjangoModelFactory):
    class Meta:
        model = Role
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Role {n}")
```

#### DeviceFactory

```python
class DeviceFactory(DjangoModelFactory):
    class Meta:
        model = Device

    name = factory.Sequence(lambda n: f"device-{n:03d}")
    location = factory.SubFactory(LocationFactory)
    device_type = factory.SubFactory(DeviceTypeFactory)
    role = factory.SubFactory(RoleFactory)

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Device).first()
```

#### InterfaceFactory

```python
class InterfaceFactory(DjangoModelFactory):
    class Meta:
        model = Interface

    name = factory.Sequence(lambda n: f"GigabitEthernet0/{n}")
    device = factory.SubFactory(DeviceFactory)
    type = "1000base-t"

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Interface).first()
```

#### VLANFactory

```python
class VLANFactory(DjangoModelFactory):
    class Meta:
        model = VLAN

    vid = factory.Sequence(lambda n: (n % 4094) + 1)
    name = factory.LazyAttribute(lambda o: f"VLAN{o.vid}")

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(VLAN).first()

    @factory.post_generation
    def locations(self, create, extracted, **kwargs):
        """Add locations after VLAN creation (M2M in Nautobot 3.x)."""
        if not create:
            return
        if extracted:
            for loc in extracted:
                self.locations.add(loc)
```

#### MACAddressHistoryFactory

```python
class MACAddressHistoryFactory(DjangoModelFactory):
    class Meta:
        model = MACAddressHistory

    device = factory.SubFactory(DeviceFactory)
    interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.device))
    mac_address = factory.Sequence(lambda n: f"00:11:22:33:{(n // 256):02X}:{(n % 256):02X}")
    vlan = factory.SubFactory(VLANFactory)
    last_seen = factory.LazyFunction(timezone.now)
```

**Critical point**: `interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.device))` — the interface is created on the same device as the factory's device. This avoids violating the `interface.device == device` constraint.

#### ARPEntryFactory

```python
class ARPEntryFactory(DjangoModelFactory):
    class Meta:
        model = ARPEntry

    device = factory.SubFactory(DeviceFactory)
    interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.device))
    ip_address = factory.Sequence(lambda n: f"10.0.{(n // 256) % 256}.{n % 256}")
    ip_address_object = None
    mac_address = factory.Sequence(lambda n: f"00:AA:BB:CC:{(n // 256):02X}:{(n % 256):02X}")
    last_seen = factory.LazyFunction(timezone.now)
```

#### TopologyConnectionFactory

```python
class TopologyConnectionFactory(DjangoModelFactory):
    class Meta:
        model = TopologyConnection

    local_device = factory.SubFactory(DeviceFactory)
    local_interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.local_device))
    remote_device = factory.SubFactory(DeviceFactory)
    remote_interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.remote_device))
    protocol = TopologyConnection.Protocol.LLDP
    last_seen = factory.LazyFunction(timezone.now)
```

### 4.4 Mock patterns

**Mocking network calls** (Nornir, NAPALM, Netmiko) — always via `unittest.mock`:

```python
from unittest.mock import MagicMock, patch

@patch("nautobot_netdb_tracking.jobs._base.InitNornir")
@patch("nautobot_netdb_tracking.jobs._base.NautobotORMInventory", None)
def test_job_commit_mode(self, mock_init_nornir, device_with_platform, interface):
    mock_nr = MagicMock()
    mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}
    mock_init_nornir.return_value = mock_nr

    mock_host_result = MagicMock()
    mock_host_result.failed = False
    mock_host_result.result = {
        "mac_table": [
            {"interface": "GigabitEthernet0/1", "mac": "AA:BB:CC:DD:EE:FF", "vlan": 100}
        ],
        "arp_table": [],
    }
    mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

    job = CollectMACARPJob()
    job.logger = MagicMock()
    result = job.run(
        device=device_with_platform,
        workers=1,
        timeout=30,
        commit=True,
        collect_mac=True,
        collect_arp=True,
    )
    assert result["success"] is True
```

**Mocking the logger**:

```python
job = MyJob()
job.logger = MagicMock()
# Then verify calls
job.logger.error.assert_called_once()
```

### 4.5 How Jobs Are Tested

**Standard pattern**:

1. Mock `InitNornir` and `NautobotORMInventory`
2. Configure `mock_nr.run.return_value` with result data
3. Call `job.run(...)` directly
4. Verify stats, objects created in DB, and logger calls

**Test dry-run** :

```python
def test_dry_run_creates_no_records(self, mock_init_nornir, device_with_platform, interface):
    # ... setup mock ...
    result = job.run(..., commit=False, ...)
    assert MACAddressHistory.objects.count() == 0
```

**Test NetDB logic (UPDATE vs INSERT)** :

```python
def test_update_existing_entry(self, device, interface):
    existing = MACAddressHistory(...)
    existing.validated_save()
    first_seen_before = existing.first_seen

    entry, created = MACAddressHistory.update_or_create_entry(
        device=device, interface=interface, mac_address="00:11:22:33:44:55"
    )
    assert created is False
    assert entry.first_seen == first_seen_before  # first_seen not modified
    assert entry.last_seen > existing.last_seen   # last_seen updated
```

**Test total failure (RuntimeError)**:

```python
def test_all_devices_failed_raises_runtime_error(self, mock_init_nornir, device_with_platform):
    mock_nr = MagicMock()
    mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}
    mock_init_nornir.return_value = mock_nr

    mock_host_result = MagicMock()
    mock_host_result.failed = True
    mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

    job = CollectMACARPJob()
    job.logger = MagicMock()

    with pytest.raises(RuntimeError):
        job.run(...)
    assert job.stats["devices_success"] == 0
```

### 4.6 FilterSet Input Format in Tests (CRITICAL)

**Absolute rule**: `NaturalKeyOrPKMultipleChoiceFilter` (used for FK fields like `device`, `interface`, `vlan`, `location`, `device_role`) expects **input as a list of strings**.

```python
# BAD — bare value for FK filters
filterset = MACAddressHistoryFilterSet({"device": device.pk})
filterset = MACAddressHistoryFilterSet({"device": device.name})

# GOOD — wrap FK/PK values in a list of strings
filterset = MACAddressHistoryFilterSet({"device": [str(device.pk)]})
filterset = MACAddressHistoryFilterSet({"device": [device.name]})

# Complete test example
@pytest.mark.django_db
def test_filter_by_device(self, device, interface):
    mac = MACAddressHistoryFactory(device=device, interface=interface)
    other_mac = MACAddressHistoryFactory()  # Autre device

    filterset = MACAddressHistoryFilterSet({"device": [str(device.pk)]})
    qs = filterset.qs

    assert mac in qs
    assert other_mac not in qs

# CharFilter — simple string (not a list)
filterset = MACAddressHistoryFilterSet({"mac_address": "00:11:22"})
filterset = MACAddressHistoryFilterSet({"q": "search term"})
filterset = MACAddressHistoryFilterSet({"ip_address": "192.168"})
```

---

## 5. Plugin Configuration

Sources: `nautobot_netdb_tracking/__init__.py`, `nautobot_netdb_tracking/signals.py`

### 5.1 NautobotAppConfig — All Attributes

File: `/Users/thomas/AzQore/nautobot_netdb_tracking/nautobot_netdb_tracking/__init__.py`

```python
from importlib.metadata import metadata
from nautobot.apps import NautobotAppConfig

__version__ = metadata("nautobot-netdb-tracking")["Version"]

class NautobotNetDBTrackingConfig(NautobotAppConfig):
    name = "nautobot_netdb_tracking"          # Python module name
    verbose_name = "NetDB Tracking"           # name displayed in the UI
    version = __version__                     # from importlib.metadata (dynamic)
    author = "Thomas"
    author_email = "thomas@networktocode.com"
    description = "Track MAC addresses, ARP entries, and network topology from network devices"
    base_url = "netdb-tracking"               # URL prefix: /plugins/netdb-tracking/
    required_settings = []                    # no mandatory settings
    min_version = "3.0.6"
    max_version = "3.99"
    default_settings = {
        "retention_days": 90,
        "purge_enabled": True,
        "nornir_workers": 50,
        "device_timeout": 30,
        "auto_create_cables": False,
        "mac_format": "colon_upper",  # colon_upper, colon_lower, dash_upper, dash_lower
    }

    def ready(self) -> None:
        """Hook called when Django app is ready."""
        super().ready()
        from nautobot_netdb_tracking.signals import register_signals
        register_signals(sender=self.__class__)
        self._fix_job_grouping()

    @staticmethod
    def _fix_job_grouping() -> None:
        """Ensure plugin jobs are grouped under 'NetDB Tracking'.

        Nautobot's register_jobs() resets grouping to the module path on startup.
        The post_migrate signal only fires when this plugin has new migrations.
        This method runs on every startup via ready() to fix the grouping.

        Uses QuerySet.update() to bypass validated_save() which would overwrite
        the grouping field.
        """
        from django.db import OperationalError, ProgrammingError
        try:
            from nautobot.extras.models import Job
            Job.objects.filter(
                module_name__startswith="nautobot_netdb_tracking.jobs"
            ).update(grouping="NetDB Tracking")
        except (OperationalError, ProgrammingError):
            # Tables may not exist yet during initial migration
            pass

config = NautobotNetDBTrackingConfig
```

**Important points**:

- `version` is loaded dynamically via `importlib.metadata` (not hardcoded)
- `_fix_job_grouping()` runs on every startup via `ready()` to counter the grouping reset by `register_jobs()`
- `try/except (OperationalError, ProgrammingError)` protects against the case where tables don't exist yet (initial migration)

### 5.2 default_settings

| Setting | Default Value | Type | Description |
| ------- | ------------- | ---- | ----------- |
| `retention_days` | 90 | int | Data retention period in days |
| `purge_enabled` | True | bool | Enable automatic purge |
| `nornir_workers` | 50 | int | Parallel workers for collection |
| `device_timeout` | 30 | int | Timeout per device in seconds |
| `auto_create_cables` | False | bool | Automatic cable creation |
| `mac_format` | `"colon_upper"` | str | MAC display format (colon_upper, colon_lower, dash_upper, dash_lower) |

Reading settings at runtime:

```python
from django.conf import settings

plugin_settings = settings.PLUGINS_CONFIG.get("nautobot_netdb_tracking", {})
retention_days = plugin_settings.get("retention_days", 90)
```

### 5.3 required_settings

```python
required_settings = []  # No mandatory settings
```

### 5.4 Registered Signals (signals.py)

File: `/Users/thomas/AzQore/nautobot_netdb_tracking/nautobot_netdb_tracking/signals.py`

#### Function `register_signals(sender)`

Called from `ready()` with `sender=self.__class__` (the AppConfig) to scope signals to this plugin only:

```python
def register_signals(sender):
    post_migrate.connect(_enable_plugin_jobs, sender=sender)
    post_migrate.connect(_ensure_interface_down_status, sender=sender)
```

#### `_enable_plugin_jobs(sender, **kwargs)`

`post_migrate` handler that enables and groups jobs:

```python
def _enable_plugin_jobs(sender, **kwargs):
    from nautobot.extras.models import Job
    updated = Job.objects.filter(
        module_name__startswith="nautobot_netdb_tracking.jobs"
    ).update(enabled=True, grouping="NetDB Tracking")
    if updated:
        logger.info("NetDB Tracking: enabled %d jobs", updated)
```

#### `_ensure_interface_down_status(sender, **kwargs)`

`post_migrate` handler that adds the `dcim.interface` content type to the "Down" status if not already present:

```python
def _ensure_interface_down_status(sender, **kwargs):
    interface_ct = ContentType.objects.get_for_model(Interface)
    status_down = Status.objects.filter(name="Down").first()
    if status_down is None:
        logger.warning("'Down' status not found — cannot assign to dcim.interface")
        return
    if not status_down.content_types.filter(pk=interface_ct.pk).exists():
        status_down.content_types.add(interface_ct)
        logger.info("Added 'Down' status to dcim.interface content type")
```

#### Utility Functions (non-signals)

```python
def get_retention_days() -> int:
    """Get retention period in days from plugin settings. Default: 90."""

def is_purge_enabled() -> bool:
    """Check if automatic purge is enabled in plugin settings."""

def purge_old_records() -> dict[str, int]:
    """Purge records older than the retention period.
    Returns: {"mac_addresses": int, "arp_entries": int, "topology_connections": int}
    """

def get_stale_records_count(days: int = 7) -> dict[str, int]:
    """Get count of records not seen in the specified number of days."""
```

### 5.5 ready() method — Complete Pattern

```python
def ready(self) -> None:
    """Hook called when Django app is ready.

    Called by Django after all apps are loaded. Used to:
    1. Import signal handlers (must be done here, not at module level)
    2. Fix job grouping on every startup
    """
    super().ready()
    # Always import signals here, never at module level
    from nautobot_netdb_tracking.signals import register_signals
    register_signals(sender=self.__class__)
    self._fix_job_grouping()
```

**Why import signals in `ready()`**: models are not yet available when the `__init__.py` module loads. Importing in `ready()` ensures all models are loaded before establishing signal connections.

---

## 6. pyproject.toml — Exact Configuration

File: `/Users/thomas/AzQore/nautobot_netdb_tracking/pyproject.toml`

### 6.1 Exact Dependencies

```toml
[tool.poetry.dependencies]
python = ">=3.10,<3.14"
nautobot = "^3.0.6"
nornir = "^3.4.0"
nornir-nautobot = "^4.0.0"
nautobot-plugin-nornir = "^3.0.0"
nornir-napalm = "^0.5.0"
nornir-netmiko = "^1.0.0"
napalm = "^5.0.0"
netmiko = "^4.3.0"
```

### 6.2 Dev dependencies

```toml
[tool.poetry.group.dev.dependencies]
pytest = "^8.0.0"
pytest-cov = "^4.1.0"
pytest-django = "^4.8.0"
factory-boy = "^3.3.0"
coverage = "^7.4.0"
ruff = "^0.2.0"
pylint = "^3.0.0"
pylint-django = "^2.5.0"
pre-commit = "^3.6.0"
```

**Note**: no `black` — ruff alone is used for formatting.

### 6.3 pytest configuration (ini_options)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
addopts = "-v --tb=short"
DJANGO_SETTINGS_MODULE = "tests.test_settings"
```

### 6.4 Coverage configuration

```toml
[tool.coverage.run]
source = ["nautobot_netdb_tracking"]
branch = true
omit = [
    "*/migrations/*",
    "*/tests/*",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
fail_under = 80
```

### 6.5 Ruff configuration

```toml
[tool.ruff]
line-length = 120
target-version = "py310"
extend-exclude = ["migrations"]

[tool.ruff.lint]
select = [
    "E",     # pycodestyle errors
    "W",     # pycodestyle warnings
    "F",     # Pyflakes
    "I",     # isort
    "N",     # pep8-naming
    "D",     # pydocstring
    "UP",    # pyupgrade
    "B",     # flake8-bugbear
    "C4",    # flake8-comprehensions
    "DJ",    # flake8-django
    "SIM",   # flake8-simplify
    "RUF",   # Ruff-specific rules
]
ignore = [
    "D100",   # Missing docstring in public module
    "D104",   # Missing docstring in public package
    "D106",   # Missing docstring in public nested class
    "D203",   # 1 blank line required before class docstring
    "D213",   # Multi-line docstring summary should start at the second line
    "D401",   # First line of docstring should be in imperative mood
    "D406",   # Section name should end with a newline
    "D407",   # Missing dashed underline after section
    "D413",   # Missing blank line after last section
    "RUF012", # Mutable class attributes (Django admin/Meta classes are standard patterns)
    "SIM102", # Nested if statements (sometimes more readable)
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["D", "S101"]
"**/migrations/*" = ["D", "E501", "I"]

[tool.ruff.lint.isort]
known-first-party = ["nautobot_netdb_tracking"]
known-third-party = ["nautobot"]
```

### 6.6 Pylint configuration

```toml
[tool.pylint.master]
ignore = ["migrations", "tests"]
load-plugins = ["pylint_django"]
django-settings-module = "tests.test_settings"

[tool.pylint.messages_control]
disable = [
    "missing-module-docstring",
    "too-few-public-methods",
    "duplicate-code",
]

[tool.pylint.format]
max-line-length = 120
```

### 6.7 Build system

```toml
[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```

### 6.8 Package metadata

```toml
[tool.poetry]
name = "nautobot-netdb-tracking"
version = "1.0.0"
description = "Nautobot plugin for tracking MAC addresses, ARP entries, and network topology (NetDB)"
authors = ["Thomas <thomas@networktocode.com>"]
license = "Apache-2.0"
readme = "README.md"
keywords = ["nautobot", "nautobot-plugin", "netdb", "mac-tracking", "arp", "topology"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Plugins",
    "Framework :: Django",
    "Intended Audience :: System Administrators",
    "License :: OSI Approved :: Apache Software License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: System :: Networking",
]
packages = [{ include = "nautobot_netdb_tracking" }]
```

---

## 7. Swarm Mode Patterns

Source: `CLAUDE.md` (section "Swarm Mode")

### 7.1 When to Use Swarm

**Use the swarm**:

- Multi-file refactoring (models + views + tables + filters + templates)
- Adding tests for multiple independent modules
- Auditing/reviewing different parts of the codebase
- Implementing independent features in parallel
- Exploratory research across multiple domains simultaneously

**Do NOT use the swarm**:

- Sequential tasks with dependencies (migration before tests, model before view)
- Modifying a single file
- Trivial tasks (< 3 steps)

### 7.2 Swarm Protocol

1. **Decompose** the task into independent subtasks (no cross-dependencies)
2. **Create a TaskList** to track overall progress
3. **Launch agents in parallel** in a single message (multiple `Task` tool calls)
4. **Each agent** receives:
   - A clear context (relevant files, precise objective)
   - Project conventions (CLAUDE.md, existing patterns)
   - Explicit instructions: research only vs writing code
5. **Consolidate** results and verify inter-agent consistency
6. **Validate** with `ruff check` + `ruff format --check` on everything

### 7.3 Available Agent Types

| Agent | Usage | Tools |
| ----- | ----- | ----- |
| `Explore` | Quick codebase search (files, patterns, architecture) | Glob, Grep, Read |
| `Plan` | Implementation plan design (architecture, trade-offs) | Glob, Grep, Read |
| `general-purpose` | Complex multi-step tasks (research + execution) | All |
| `Bash` | Terminal commands (git, docker, npm) | Bash |
| `code-simplifier` | Simplification and refactoring of existing code | All |
| `nautobot-developer` | Nautobot 3.x dev: models, views, API, jobs, filters, migrations | Read, Write, Edit, Bash, Glob, Grep |
| `nautobot-code-reviewer` | Nautobot 3.x review: anti-patterns, deprecated APIs, security, performance | Read, Write, Edit, Bash, Glob, Grep |

### 7.4 Swarm Decomposition Examples

#### Codebase audit (4 agents in parallel)

```text
Agent 1 (Explore): Audit models.py — fields, constraints, indexes, clean()
Agent 2 (Explore): Audit jobs/ — error handling, Nornir patterns, stats
Agent 3 (Explore): Audit views.py + templates/ — UI standards, pagination
Agent 4 (Explore): Audit api/ — serializers, viewsets, permissions
```

#### Adding tests (3 agents in parallel)

```text
Agent 1 (general-purpose): Write tests for models (validation, constraints)
Agent 2 (general-purpose): Write tests for filters (FK filters, CharFilters)
Agent 3 (general-purpose): Write tests for views (list, detail, permissions)
```

#### Multi-component feature (sequential + parallel)

```text
Phase 1 (sequential):
  Agent Plan: Design the architecture (model, API, UI)

Phase 2 (parallel, after plan validation):
  Agent 1: Implement model + migration
  Agent 2: Implement serializer + API viewset
  Agent 3: Implement table + filter + template

Phase 3 (sequential):
  Consolidation: verify consistency, ruff check, tests
```

### 7.5 Critical Rules for Agents

- **Read before writing**: each agent MUST read existing files before modifying
- **No conflicts**: two agents must NEVER modify the same file
- **Conventions**: each agent follows CLAUDE.md standards (`validated_save`, type hints, etc.)
- **Autonomy**: the agent must be able to complete its task without depending on another agent
- **Report**: each agent returns a clear summary of what it did/found

---

## Official References

1. **Nautobot Core** : <https://docs.nautobot.com/projects/core/en/stable/>
2. **Nautobot App Development** : <https://docs.nautobot.com/projects/core/en/stable/development/apps/>
3. **Nautobot Plugin Nornir** : <https://docs.nautobot.com/projects/plugin-nornir/en/latest/>
4. **Network-to-Code Cookiecutter** : <https://github.com/nautobot/cookiecutter-nautobot-app>
5. **Nornir** : <https://nornir.readthedocs.io/>
6. **NAPALM** : <https://napalm.readthedocs.io/>
7. **Django** : <https://docs.djangoproject.com/en/5.0/>
8. **Bootstrap 5** : <https://getbootstrap.com/docs/5.3/>
9. **Factory Boy** : <https://factoryboy.readthedocs.io/>
10. **pytest-django** : <https://pytest-django.readthedocs.io/>

---

**Last updated**: 2026-02-18
**Based on**: `nautobot-netdb-tracking` v1.0.0 (reference commit: 2026-02-12)
