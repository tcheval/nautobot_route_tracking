# Convention: Nautobot Plugin

> **Version:** 1.0
> **Scope:** Nautobot 3.x plugin development patterns and constraints
> **Requires:** `_convention/_core.md`

**Extends core:** This file adds Nautobot-specific rules. It NEVER overrides `_core.md` principles.

---

## Table of Contents

- [1. Architecture](#1-architecture)
- [2. Data Model](#2-data-model)
- [3. Naming Conventions](#3-naming-conventions)
- [4. Patterns](#4-patterns)
- [5. Anti-patterns](#5-anti-patterns)
- [6. Validation Rules](#6-validation-rules)

---

## 1. Architecture

```text
[Models] → [Views/API] → [Templates/Serializers]
  (data)     (logic)        (presentation)

[Jobs] → [Nornir/NAPALM] → [Network Devices]
 (task)    (framework)        (collection)
```

| Component | Responsibility | Inputs | Outputs |
| --------- | -------------- | ------ | ------- |
| `models.py` | Data model, validation, DB constraints | Django ORM | RouteEntry instances |
| `jobs/` | Collection orchestration via Nornir | Device queryset, CLI output | RouteEntry rows |
| `views.py` | UI list/detail/tab views | HTTP requests | HTML responses |
| `api/` | REST API (DRF) | HTTP requests | JSON responses |
| `filters.py` | Query filtering for UI and API | GET params | Filtered querysets |
| `tables.py` | Table rendering (django-tables2) | Querysets | HTML tables |
| `forms.py` | Filter forms for UI | Form data | Validated params |
| `navigation.py` | Menu integration | — | NavMenuTab |
| `template_content.py` | Device tab extension | Device context | Tab HTML |

### Boundary Rules

- **Owns:** RouteEntry model, route collection jobs, route UI/API, route filtering
- **Does NOT own:** Device, Interface, VRF, Platform models (Nautobot core)
- **Depends on:** `nautobot.dcim`, `nautobot.ipam`, `nautobot_plugin_nornir`, `nornir_napalm`

---

## 2. Data Model

### 2.1 RouteEntry

| Field | Type | Required | Default | Description |
| ----- | ---- | -------- | ------- | ----------- |
| `device` | FK(Device) | yes | — | Source device (CASCADE) |
| `vrf` | FK(VRF) | no | NULL | VRF context (SET_NULL) |
| `network` | CharField(50) | yes | — | CIDR notation ("10.0.0.0/8") |
| `prefix_length` | PositiveSmallIntegerField | yes | — | Prefix length (8) |
| `protocol` | CharField(20) | yes | — | Routing protocol (choices) |
| `next_hop` | CharField(50) | no | `""` | Next-hop IP or empty for connected |
| `outgoing_interface` | FK(Interface) | no | NULL | Egress interface (SET_NULL) |
| `metric` | PositiveIntegerField | yes | `0` | Route metric |
| `admin_distance` | PositiveSmallIntegerField | yes | `0` | Administrative distance |
| `is_active` | BooleanField | yes | `True` | Route active in RIB |
| `routing_table` | CharField(100) | yes | `"default"` | Raw VRF name from device |
| `first_seen` | DateTimeField | yes | auto | First observation timestamp |
| `last_seen` | DateTimeField | yes | — | Last observation timestamp |

**Constraints:**

- UniqueConstraint on `(device, vrf, network, next_hop, protocol)` — ECMP = separate rows
- Partial UniqueConstraint for `vrf IS NULL` (PostgreSQL NULL uniqueness)
- Protocol values normalized to lowercase before storage

### Relationships

```text
RouteEntry N──1 Device      (via device, CASCADE)
RouteEntry N──1 VRF         (via vrf, SET_NULL, nullable)
RouteEntry N──1 Interface   (via outgoing_interface, SET_NULL, nullable)
```

---

## 3. Naming Conventions

| Category | Pattern | Good Example | Bad Example |
| -------- | ------- | ------------ | ----------- |
| Plugin package | `nautobot_<name>` | `nautobot_route_tracking` | `route-tracking` |
| Models | `PascalCase`, singular | `RouteEntry` | `route_entries` |
| Jobs | `PascalCase` + `Job` suffix | `CollectRoutesJob` | `collect_routes` |
| Nornir tasks | `_snake_case` module-level | `_collect_routes_eos(task)` | `class EosCollector` |
| Parsers | `_parse_<platform>_routes()` | `_parse_eos_routes()` | `parse_routes()` |
| Constants | `UPPER_SNAKE_CASE` | `SUPPORTED_PLATFORMS` | `supportedPlatforms` |
| Filters | `<Model>FilterSet` | `RouteEntryFilterSet` | `RouteFilter` |
| Tables | `<Model>Table` | `RouteEntryTable` | `RoutesTable` |
| Templates | `<app_name>/<template>.html` | `nautobot_route_tracking/device_route_tab.html` | `route_tab.html` |
| API serializers | `<Model>Serializer` | `RouteEntrySerializer` | `RouteSerializer` |

---

## 4. Patterns

### 4.1 UPDATE/INSERT (NetDB Logic)

**When:** Storing collected route data from network devices.

**Why:** History only contains actual changes, not redundant snapshots. Supports core principle 1.8 (Predictable Output) — same route state produces same DB state.

```python
@classmethod
def update_or_create_entry(cls, device, network, protocol, vrf=None, next_hop="", **kwargs):
    with transaction.atomic():
        existing = cls.objects.select_for_update().filter(
            device=device, vrf=vrf, network=network,
            next_hop=next_hop, protocol=protocol,
        ).first()
        if existing:
            existing.last_seen = timezone.now()
            for field, value in kwargs.items():
                setattr(existing, field, value)
            existing.validated_save()
            return existing, False
        entry = cls(
            device=device, vrf=vrf, network=network,
            next_hop=next_hop, protocol=protocol,
            last_seen=timezone.now(), **kwargs
        )
        entry.validated_save()
        return entry, True
```

### 4.2 Nornir Parallel Collection

**When:** Collecting data from multiple network devices.

**Why:** Single `nr.run()` call with parallel workers. Supports core principle 1.1 (KISS) — no manual threading or sequential loops.

```python
nr = self.initialize_nornir(devices=devices, workers=workers, timeout=timeout)
results = nr.run(task=_collect_routes_task, severity_level=logging.DEBUG)
```

### 4.3 Platform-Specific Parsing

**When:** Processing CLI output from different network platforms.

**Why:** Each platform has its own output format. Supports core principle 1.6 (Separation of Concerns) — parsers are isolated per platform.

```python
def _collect_routes_task(task: Task) -> Result:
    platform = task.host.platform
    if platform == "arista_eos":
        return _collect_routes_eos(task)
    elif platform == "cisco_ios":
        return _collect_routes_ios(task)
    return Result(host=task.host, failed=True, result=f"Unsupported: {platform}")
```

### 4.4 Graceful Degradation

**When:** One device fails during parallel collection.

**Why:** One device failure must not crash the entire job. Supports core principle 1.11 (Fail Loud) — errors are logged per device, but the job continues.

```python
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(msg)  # ONLY if zero successes
```

---

## 5. Anti-patterns

### 5.1 Direct `.save()` Instead of `validated_save()`

**Problem:** Bypasses Nautobot validation (clean, clean_fields). Invalid data reaches the database.

**Violates:** 1.11 Fail Loud, Fail Early

```python
# BAD
entry.save()
RouteEntry.objects.create(device=device, network="10.0.0.0/8")
```

**Fix:**

```python
# GOOD
entry.validated_save()
```

### 5.2 Using `napalm_get` Instead of `napalm_cli`

**Problem:** `napalm_get(getters=["get_route_to"])` returns incomplete/unreliable data across platforms. Platform-specific CLI with dedicated parsers is the only reliable approach.

**Violates:** 1.8 Predictable Output

```python
# BAD
task.run(task=napalm_get, getters=["get_route_to"])
```

**Fix:**

```python
# GOOD
task.run(task=napalm_cli, commands=["show ip route | json"])
routes = _parse_eos_routes(result)
```

### 5.3 Sequential Device Loop

**Problem:** Iterating devices one by one instead of using Nornir parallel execution. O(n) time instead of O(1) with workers.

**Violates:** 1.1 KISS — Nornir already handles parallelism.

```python
# BAD
for device in devices:
    nr.run(task=collect, on=device)
```

**Fix:**

```python
# GOOD — single parallel run
results = nr.run(task=_collect_routes_task)
```

### 5.4 Hardcoded Credentials

**Problem:** Credentials in code or environment variable reads inside jobs. Nautobot SecretsGroup + nautobot_plugin_nornir handle this.

**Violates:** 1.10 No Hidden Magic (credentials should flow through the SSoT)

```python
# BAD
nr.inventory.defaults.username = "admin"
os.environ["SSH_PASSWORD"]
```

**Fix:**

```python
# GOOD — credentials resolved by CredentialsNautobotSecrets via SecretsGroup
nr = self.initialize_nornir(devices=devices, workers=workers, timeout=timeout)
```

---

## 6. Validation Rules

| # | Rule | Check Method | Severity |
| - | ---- | ------------ | -------- |
| 1 | No `.save()` — always `validated_save()` | `grep -rn '\.save()' nautobot_route_tracking/` | CRITICAL |
| 2 | No `import napalm` or `napalm_get` | `grep -rn 'import napalm\|napalm_get' nautobot_route_tracking/` | CRITICAL |
| 3 | No `print()` in jobs | `grep -rn 'print(' nautobot_route_tracking/jobs/` | CRITICAL |
| 4 | No hardcoded credentials | `grep -rn 'password\s*=' nautobot_route_tracking/` | CRITICAL |
| 5 | Protocol values lowercase | Unit test on `clean_fields()` | WARNING |
| 6 | Jobs registered via `register_jobs()` | `grep 'register_jobs' nautobot_route_tracking/jobs/__init__.py` | CRITICAL |
| 7 | Nornir tasks at module level | Review `jobs/*.py` for class-level task defs | WARNING |
| 8 | Templates use `inc/table.html` | `grep 'render_table' nautobot_route_tracking/templates/` | WARNING |
| 9 | Filters use list values for FK | Unit tests in `test_filters.py` | WARNING |

### Automated Enforcement

| Rule # | Enforcement | Tool/Config |
| ------ | ----------- | ----------- |
| 1 | ⚠️ Partial | `ruff` cannot detect; grep in CI |
| 2 | ⚠️ Partial | grep in CI |
| 3 | ✅ Enforced | `ruff` rule T201 |
| 4 | ⚠️ Partial | `gitleaks` pre-commit hook |
| 5 | ✅ Enforced | Unit test `test_models.py` |
| 6 | ❌ Manual | Code review |
| 7 | ❌ Manual | Code review |
| 8 | ❌ Manual | Code review |
| 9 | ✅ Enforced | Unit test `test_filters.py` |
