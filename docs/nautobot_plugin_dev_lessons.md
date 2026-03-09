# Nautobot Plugin Development - Lessons Learned

Survival guide for Nautobot 3.x plugin development. Each section documents a pitfall encountered in production and the correct solution.

## Table of Contents

- [Nornir and Parallelism](#nornir-and-parallelism)
- [NautobotORMInventory and NAPALM](#nautobotorminventory-and-napalm)
- [Nautobot 3.x - Models and ORM](#nautobot-3x---models-and-orm)
- [Nautobot 3.x - Jobs](#nautobot-3x---jobs)
- [Nautobot 3.x - API and Serializers](#nautobot-3x---api-and-serializers)
- [Nautobot 3.x - Tests](#nautobot-3x---tests)
- [Django - Views and Templates](#django---views-and-templates)
- [Custom Views with Filter Sidebar and Pagination](#custom-views-with-filter-sidebar-and-pagination)
- [Django - Signals](#django---signals)
- [Python - Code Quality](#python---code-quality)
- [Configuration and Packaging](#configuration-and-packaging)
- [FakeNOS and Integration Tests](#fakenos-and-integration-tests)
- [Nautobot Status - Semantic Pitfalls](#nautobot-status---semantic-pitfalls)
- [Docker - Hot Deployment of the Plugin](#docker---hot-deployment-of-the-plugin)

---

## Nornir and Parallelism

### Golden-config Pattern (REFERENCE)

The reference pattern is from [nautobot-app-golden-config](https://github.com/nautobot/nautobot-app-golden-config/tree/v3.0.2/nautobot_golden_config/nornir_plays). Every Nornir job must follow it.

**Correct**: a single `nr.run()` across all hosts in parallel.

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

### Mistakes to NEVER Make

| Anti-pattern | Why it is wrong |
| ------------ | --------------- |
| Serial reachability check loop BEFORE `nr.run()` | Defeats parallelism. One TCP check per device = N * 5s serially |
| `nr.filter(name=device_name).run()` in a loop | Same problem — disguised sequential execution |
| Retry logic after `nr.run()` with `time.sleep()` | Blocks the entire job. Nornir handles timeouts natively |
| `tenacity` retry decorator on `_collect_from_host()` | Unnecessary complexity. If a device fails, it fails — log and move on |
| `_collect_from_host()` per-device method | Dead code when using `_combined_*_task` with `nr.run()` |

### Combined Task (correct pattern)

To collect multiple data types from the same host in a single SSH session:

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

### NornirSubTaskError: Extracting the Root Cause (CRITICAL)

When `task.run()` fails (SSH timeout, connection refused, auth failure), Nornir raises `NornirSubTaskError`. The `exc.result` attribute is a **`MultiResult`** (list of `Result`), NOT a single `Result`. Accessing `exc.result.exception` never works because lists do not have an `.exception` attribute.

```python
# BAD — exc.result is a list, .exception does not exist
# Falls back to str(exc) = "Subtask: collect_mac_table_task (failed)"
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

**Before** (useless message):

```text
[error] [arista-sw01] Collection failed: MAC: Subtask: collect_mac_table_task (failed)
```

**After** (visible root cause):

```text
[error] [arista-sw01] Collection failed: MAC: MAC collection failed (NAPALM + TextFSM):
  TCP connection to device failed.
  Common causes: 1. Incorrect hostname or IP address. 2. Wrong TCP port.
  Device settings: arista_eos 172.28.0.11:22
```

### Partial Job: Do Not Raise RuntimeError When devices_failed > 0

A collection job running on 1500 devices will inevitably have some failures (maintenance, outage, ACL). Marking the entire job as FAILURE prevents monitoring from distinguishing a real problem from normal operation.

```python
# BAD — 3 devices down out of 1500 = job FAILURE + RuntimeError in Celery
if self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

# GOOD — FAILURE only if NO device succeeded (global infrastructure outage)
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

return {
    "success": self.stats["devices_failed"] == 0,  # True if 100% success
    "summary": summary_msg,
    **self.stats,
}
```

| Scenario | Before | After |
| -------- | ------ | ----- |
| 1500/1500 OK | SUCCESS | SUCCESS |
| 1497/1500 OK, 3 down | FAILURE + RuntimeError | SUCCESS (success=False in result) |
| 0/1500 OK (infra outage) | FAILURE + RuntimeError | FAILURE + RuntimeError |

### Mocking Nornir in Tests

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

## NautobotORMInventory and NAPALM

### Problem: network_driver != napalm_driver

`NautobotORMInventory` uses `Platform.network_driver` (e.g., `arista_eos`) for `host.platform`. But NAPALM expects `Platform.napalm_driver` (e.g., `eos`). Without correction, NAPALM fails to find the correct driver.

### Problem: Host-level extras overwrite defaults

Extras configured per host in `NautobotORMInventory` (via config context) **replace** the defaults passed to InitNornir, instead of merging them. This causes loss of `transport`, `timeout`, etc.

### Solution: Post-init injection

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

### Config Context for Custom SSH Port

The custom SSH port (e.g., FakeNOS on ports 6001-6005) must be in the device's config context, under the `nautobot_plugin_nornir.connection_options` key:

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

## Nautobot 3.x - Models and ORM

### IPAddress: Fields Renamed Since Nautobot 2.x

| Nautobot 2.x | Nautobot 3.x | Notes |
| ------------ | ------------ | ----- |
| `address="10.0.0.1/24"` | `host="10.0.0.1"` + `mask_length=24` | Split into two fields |
| `namespace=ns` | `parent=prefix` | The namespace is carried by the Prefix |

### Job.grouping Overwritten by validated_save()

The `grouping` field of a Job is overwritten by `validated_save()`. Use `QuerySet.update()`:

```python
Job.objects.filter(module_name__startswith="nautobot_netdb_tracking").update(
    enabled=True, grouping="NetDB Tracking"
)
```

### validated_save() ALWAYS

Never use `.save()` or `objects.create()`. Always use `instance.validated_save()` or the custom `update_or_create_entry` pattern.

### select_related / prefetch_related

Never query inside a loop. Pre-fetch:

```python
# BAD — N+1 queries
for mac in MACAddressHistory.objects.all():
    print(mac.device.name)

# GOOD — 1 query
for mac in MACAddressHistory.objects.select_related("device", "interface"):
    print(mac.device.name)
```

### Cable: Status Required in Nautobot 3.x

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

### UniqueConstraint: Naming Convention

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

### natural_key_field_lookups for Models

Nautobot 3.x models must define `natural_key_field_lookups` in their Meta for natural key support in the API and filters. Without this, natural key lookups fail silently:

```python
class MACAddressHistory(PrimaryModel):
    class Meta:
        natural_key_field_lookups = {
            "device__name": "device",
            "interface__name": "interface",
            "mac_address": "mac_address",
        }
```

### Race Condition: count() Then delete()

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

## Nautobot 3.x - Jobs

### Job Registration (MANDATORY)

`jobs/__init__.py` MUST call `register_jobs()`. Without it, jobs are importable but do not appear in the UI:

```python
from nautobot.core.celery import register_jobs
from myapp.jobs.my_job import MyJob

jobs = [MyJob]
register_jobs(*jobs)
```

### ScriptVariable: Accessing Attributes

Defaults and constraints are in `field_attrs`, not as direct attributes:

```python
# BAD
job.retention_days.default  # AttributeError
job.retention_days.min_value  # AttributeError

# GOOD
job.retention_days.field_attrs["initial"]  # 90
job.retention_days.field_attrs["min_value"]  # 1
```

### Plugin Registration in Tests

`test_settings.py` needs BOTH:

```python
PLUGINS = ["nautobot_netdb_tracking"]           # for nautobot-server (CI)
INSTALLED_APPS.append("nautobot_netdb_tracking")  # for pytest-django
```

`django.setup()` does NOT process `PLUGINS`. `nautobot-server` does NOT read `DJANGO_SETTINGS_MODULE`.

### CI: Migrations

Use `nautobot-server init` then add the plugin, not `django-admin`:

```yaml
- name: Initialize Nautobot configuration
  run: |
    poetry run nautobot-server init
    echo 'PLUGINS = ["nautobot_netdb_tracking"]' >> ~/.nautobot/nautobot_config.py
- name: Run migrations
  run: poetry run nautobot-server makemigrations nautobot_netdb_tracking
```

---

## Nautobot 3.x - API and Serializers

### select_related in API ViewSets

`NautobotModelViewSet` instances must include **all** FK fields used by the serializer in `select_related()`. Otherwise, each serialized object generates additional queries (N+1):

```python
# BAD — ip_address_object is in the serializer but not in select_related
class ARPEntryViewSet(NautobotModelViewSet):
    queryset = ARPEntry.objects.select_related(
        "device", "device__location", "interface",
    ).prefetch_related("tags")

# GOOD — all serializer FK fields are pre-loaded
class ARPEntryViewSet(NautobotModelViewSet):
    queryset = ARPEntry.objects.select_related(
        "device", "device__location", "interface", "ip_address_object",
    ).prefetch_related("tags")
```

**Rule**: for every FK field in the serializer's `fields`, verify it is in the corresponding ViewSet's `select_related()` (both UI and API).

### Nested Serializers: Do Not Create Dead Code

Do not declare "nested" or "lite" serializers in anticipation. A serializer that is not imported anywhere is dead code that creates confusion and technical debt:

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

## Nautobot 3.x - Tests

### FilterSet: Input Formats

| Filter type | Expected format | Example |
| ----------- | --------------- | ------- |
| `NaturalKeyOrPKMultipleChoiceFilter` (FK) | List of strings | `{"device": [str(device.pk)]}` |
| `CharFilter` | Simple string | `{"mac_address": "00:11:22"}` |

### NaturalKeyOrPKMultipleChoiceFilter: to_field_name

`NaturalKeyOrPKMultipleChoiceFilter` uses `to_field_name="name"` by default for natural key lookup. But some Nautobot models do not have a `name` field — for example `IPAddress` uses `host`:

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

### BaseTable: No configure()

Nautobot `BaseTable` does NOT have a `configure(request)` method. Never call it:

```python
# BAD — AttributeError
table = MACAddressHistoryTable(data)
table.configure(request)

# GOOD
table = MACAddressHistoryTable(data)
```

Null FK cells may render as `&mdash;` (HTML entity), not just `—` or `""`.

### Tab View Templates: render_table and obj_table.html

`{% render_table table %}` without a template argument uses the Nautobot `DJANGO_TABLES2_TEMPLATE` (`utilities/obj_table.html`). This template accesses `table.context` which only exists if the table was configured via `RequestConfig`. Tab views (Device/Interface tabs) create tables without `RequestConfig` — crash `AttributeError: object has no attribute 'context'`.

```django
{# BAD — crashes on tab views #}
{% render_table table %}

{# GOOD — forces a simple template that does not require table.context #}
{% render_table table "django_tables2/bootstrap5.html" %}
```

### test_settings.py: CACHES Must Include TIMEOUT

The `CACHES` config in `test_settings.py` must include `"TIMEOUT"` otherwise `KeyError: 'TIMEOUT'`:

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

### Nautobot 3.x Export: ExportTemplate Required

Nautobot 3.x uses `ExportTemplate` objects for CSV/YAML export. Without a configured `ExportTemplate`, a `?export=csv` request returns **404** (not an empty CSV or a 500 error). Tests must account for this:

```python
# GOOD — test that export without template returns 404
def test_export_without_template(self, authenticated_client):
    url = reverse("plugins:myapp:mymodel_list")
    response = authenticated_client.get(url, {"export": "csv"})
    assert response.status_code == 404
```

### API Test URLs: reverse() vs Hardcoded Paths

`reverse()` with nested namespaces (`plugins-api:myapp-api:mymodel-list`) is fragile in test environments where plugin URLs are injected into Nautobot's resolvers. The `URLResolver.namespace_dict` cache is not always properly invalidated.

**Reliable solution**: use hardcoded URL paths in API tests:

```python
# BAD — NoReverseMatch if the namespace is not properly injected
url = reverse("plugins-api:nautobot_netdb_tracking-api:macaddresshistory-list")

# GOOD — reliable, no dependency on the resolver
_API_BASE = "/api/plugins/netdb-tracking"

def _mac_list_url():
    return f"{_API_BASE}/mac-address-history/"

def _mac_detail_url(pk):
    return f"{_API_BASE}/mac-address-history/{pk}/"
```

### Mocking Nornir Jobs

See the section [Mocking Nornir in Tests](#mocking-nornir-in-tests).

The job only raises `RuntimeError` if **all** devices fail (`devices_success == 0`). For partial failures, the job returns normally with `success=False`:

```python
# Test partial failure — the job returns normally
result = job.run(...)
assert result["success"] is False
assert job.stats["devices_failed"] == 1
assert job.stats["devices_success"] > 0

# Test total failure — the job raises RuntimeError
with pytest.raises(RuntimeError):
    job.run(...)  # all devices fail
assert job.stats["devices_success"] == 0
```

### conftest.py: Use validated_save()

Test fixtures must use `validated_save()`, not `.create()` or `.save()`. This ensures that the same validations applied in production are exercised in tests:

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

### Test Coverage: Commonly Overlooked Areas

The following categories are frequently overlooked and cause regressions in production:

| Area to test | Why |
| ------------ | --- |
| Forms (`NautobotModelForm`, `NautobotFilterForm`) | Validate `query_params`, `required`, widgets, and the `clean()` method |
| TemplateExtension (`template_content.py`) | Verify HTML rendering, contexts, and N+1 queries in panels |
| Permissions on custom views | Verify that non-NautobotUIViewSet views return 403/302 for anonymous users |
| Active CI test job | The test job in `.github/workflows/ci.yml` must never be commented out |

### Permission Tests on Views

Always test that an unauthenticated user is redirected (302) or rejected (403):

```python
def test_dashboard_requires_login(client):
    """Verify anonymous users are redirected to login."""
    response = client.get("/plugins/netdb-tracking/dashboard/")
    assert response.status_code == 302
    assert "/login/" in response.url

def test_dashboard_requires_permission(authenticated_client):
    """Verify permission check is enforced."""
    # User without 'view_macaddresshistory' permission
    response = authenticated_client.get("/plugins/netdb-tracking/dashboard/")
    assert response.status_code == 403
```

---

## Django - Views and Templates

### Authentication Mixins

Custom views (non-NautobotUIViewSet) MUST have auth mixins:

```python
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin

class NetDBDashboardView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_macaddresshistory"
```

`NautobotUIViewSet` handles auth automatically. Standard Django `View` classes do NOT.

**Watch out for tab views**: views used as tabs on Device/Interface pages via `TemplateExtension` are standard Django `View` classes. They are called via AJAX from the detail page, but remain directly accessible HTTP endpoints. Without auth, any user can access the data via the direct URL:

```python
# BAD — accessible without authentication
class DeviceMACTabView(View):
    def get(self, request, pk):
        ...

# GOOD — auth + model-specific permissions
class DeviceMACTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_macaddresshistory"

    def get(self, request, pk):
        ...

class DeviceARPTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_arpentry"

class DeviceTopologyTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_topologyconnection"
```

**Rule**: each `permission_required` must correspond to the model displayed by the view, not a generic permission shared across all views.

### QueryDict.pop() vs getlist()

`QueryDict.pop(key)` returns the **last value** (a single string), not a list. For multi-value parameters (e.g., `?device=uuid1&device=uuid2`), use `request.GET.getlist()`:

```python
# BAD — returns "uuid2" (string), not ["uuid1", "uuid2"]
devices = request.GET.pop("device", None)

# GOOD — returns ["uuid1", "uuid2"]
devices = request.GET.getlist("device")
```

### Template Tags

External Django filters require an explicit `{% load %}`:

```django
{# BAD — TemplateSyntaxError #}
{% load helpers %}
{{ value|intcomma }}

{# GOOD #}
{% load helpers humanize %}
{{ value|intcomma }}
```

### Query Optimization in Views

Use DB aggregations instead of Python loops:

```python
# BAD — 3 * N queries (N = number of days)
for day_offset in range(30):
    mac_count = MACAddressHistory.objects.filter(
        first_seen__gte=start, first_seen__lte=end
    ).count()

# GOOD — 3 queries total
from django.db.models.functions import TruncDate
mac_counts = dict(
    MACAddressHistory.objects.filter(first_seen__gte=start_date)
    .annotate(date=TruncDate("first_seen"))
    .values("date")
    .annotate(count=Count("id"))
    .values_list("date", "count")
)
```

---

## Custom Views with Filter Sidebar and Pagination

When creating a custom page (not a `NautobotUIViewSet`) but wanting the native Nautobot look — sliding filter sidebar, pagination, buttons — there are 5 major pitfalls. This section documents the complete pattern.

### Pitfall 1: `generic/object_list.html` Is Coupled to NautobotUIViewSet

**DO NOT** extend `generic/object_list.html` for a custom view. This template is tightly coupled to the context provided by `NautobotHTMLRenderer`:

- `content_type.model_class` — used for `plugin_buttons`, `add_button`, `export_button`, bulk actions
- `model.is_saved_view_model` — controls the saved views section
- `table.configurable_columns` — method of `BaseTable`, absent on `tables.Table`

**Solution**: extend `base.html` and manually add the drawer + table + pagination.

### Pitfall 2: `BaseTable` Requires a `Meta.model`

`BaseTable.__init__` calls `CustomField.objects.get_for_model(model)`. If `Meta.model` is `None` (table based on dicts, not a QuerySet), it crashes with `AttributeError: 'NoneType' object has no attribute '_meta'`.

**Solution**: use `django_tables2.Table` instead of `BaseTable`:

```python
import django_tables2 as tables

class MyCustomTable(tables.Table):  # NOT BaseTable!
    col1 = tables.Column()
    col2 = tables.TemplateColumn(template_code="...")

    class Meta:
        template_name = "django_tables2/bootstrap5.html"  # MANDATORY (see pitfall 3)
        attrs = {"class": "table table-hover nb-table-headings"}
        fields = ("col1", "col2")
```

### Pitfall 3: The Default django-tables2 Template Is a Custom Nautobot Template

`DJANGO_TABLES2_TEMPLATE` is configured to `utilities/obj_table.html` in Nautobot. This template accesses `table.data.verbose_name_plural`, `permissions.change`, `bulk_edit_url`, etc. — all of which are absent for a `tables.Table` with dicts.

**Solution**: force `template_name = "django_tables2/bootstrap5.html"` in `Meta`.

### Pitfall 4: `{% filter_form_drawer %}` Has 4 Mandatory Positional Arguments

```django
{# BAD — TemplateSyntaxError: did not receive value(s) for 'filter_params' #}
{% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title %}

{# GOOD #}
{% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title filter_params=filter_params %}
```

The view MUST pass `dynamic_filter_form` (= `None`) and `filter_params` (= `[]`) in the context.

### Pitfall 5: `{% load X Y Z from library %}` Loads X, Y, Z from library

```django
{# BAD — Django looks for "helpers" and "humanize" in django_tables2 #}
{% load helpers humanize render_table from django_tables2 %}

{# GOOD — load separately #}
{% load helpers humanize %}
{% load render_table from django_tables2 %}
```

### Complete Pattern — View

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

        # ... build data (list of dicts) ...
        all_data = [{"col1": "a", "col2": "b"}, ...]

        # Paginated table
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

### Complete Pattern — Form (NautobotFilterForm)

```python
from django import forms
from nautobot.apps.forms import DynamicModelMultipleChoiceField, NautobotFilterForm
from nautobot.dcim.models import Device

class MyFilterForm(NautobotFilterForm):
    model = Device  # required by NautobotFilterForm mixins
    q = forms.CharField(required=False, label="Search")
    device = DynamicModelMultipleChoiceField(queryset=Device.objects.all(), required=False)
    # ... other fields ...
```

### Complete Pattern — Table (django_tables2.Table)

```python
import django_tables2 as tables

class MyCustomTable(tables.Table):
    col1 = tables.Column(verbose_name="Column 1")
    col2 = tables.TemplateColumn(
        template_code='{% if value %}<span class="badge bg-success">{{ value }}</span>{% endif %}',
        verbose_name="Column 2",
    )

    class Meta:
        template_name = "django_tables2/bootstrap5.html"
        attrs = {"class": "table table-hover nb-table-headings"}
        fields = ("col1", "col2")
```

### Complete Pattern — Template

```django
{% extends "base.html" %}
{% load helpers humanize %}
{% load render_table from django_tables2 %}

{% block title %}My Page{% endblock %}

{% block breadcrumbs %}
<li class="breadcrumb-item"><a href="...">Parent</a></li>
<li class="breadcrumb-item active">My Page</li>
{% endblock %}

{% block drawer %}
    {% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title filter_params=filter_params %}
{% endblock drawer %}

{% block content %}
<!-- Optional stats bar / header -->
<div class="row mb-4">...</div>

<!-- Filter + action buttons -->
<div class="d-flex justify-content-between align-items-center mb-3">
    <div>
        <button type="button" class="btn btn-sm btn-ghost-dark"
                data-nb-toggle="drawer" data-nb-target="#FilterForm_drawer">
            <i class="mdi mdi-filter"></i> Filters
        </button>
    </div>
    <div>
        <!-- Export, other action buttons -->
    </div>
</div>

<!-- Table with pagination -->
<div class="card">
    <div class="card-body p-0">
        {% render_table table %}
    </div>
</div>
{% endblock %}
```

### Quick Checklist

| Element | How |
| --- | --- |
| Table class | `tables.Table` (NOT `BaseTable`) |
| `Meta.template_name` | `"django_tables2/bootstrap5.html"` |
| `Meta.attrs` | `{"class": "table table-hover nb-table-headings"}` |
| Form class | `NautobotFilterForm` with `model = Device` |
| Template extends | `base.html` (NOT `generic/object_list.html`) |
| `{% load %}` | Separate native loads and `from library` loads |
| Drawer block | `{% filter_form_drawer %}` with 4 args |
| View context | `dynamic_filter_form=None`, `filter_params=[]` |
| Pagination | `RequestConfig(request, paginate={"per_page": 50}).configure(table)` |
| Filter button | `data-nb-toggle="drawer" data-nb-target="#FilterForm_drawer"` |

### Reference: Existing Implementation

See `SwitchReportView` in `views.py`, `SwitchReportTable` in `tables.py`, `SwitchReportFilterForm` in `forms.py`, and `switch_report.html`.

---

## Django - Signals

### post_migrate: Always Specify sender

A `post_migrate` signal without `sender` executes for **every** Django app that migrates (40+ apps in Nautobot). Specify the sender to run it only for our app:

```python
# BAD — executes 40+ times on each migrate
post_migrate.connect(enable_netdb_jobs)

# GOOD — executes once for our app only
from django.apps import apps

post_migrate.connect(
    enable_netdb_jobs,
    sender=apps.get_app_config("nautobot_netdb_tracking"),
)
```

### Signal Receiver: Handle Idempotency

The `post_migrate` handler can execute multiple times (restart, multiple migrations). Always write idempotent handlers:

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

## Python - Code Quality

### Single Normalization Function (DRY)

Never duplicate a normalization function (MAC, interface, etc.) across multiple modules. Define **one single source of truth** in the lowest module in the hierarchy (typically `models.py`) and import everywhere:

```python
# BAD — two nearly identical functions in two modules
# models.py : normalize_mac_address() → UPPERCASE
# jobs/collect_mac_arp.py : normalize_mac() → lowercase

# GOOD — one canonical function in models.py
# models.py
def normalize_mac_address(mac: str) -> str:
    """Normalize MAC to XX:XX:XX:XX:XX:XX."""
    ...

# jobs/collect_mac_arp.py — import from models
from nautobot_netdb_tracking.models import normalize_mac_address
```

If the wrapper needs to adapt the exception (e.g., `ValidationError` to `ValueError`), create a thin wrapper that delegates:

```python
def normalize_mac(mac: str) -> str:
    """Backward-compatible wrapper."""
    try:
        return normalize_mac_address(mac)
    except ValidationError as exc:
        raise ValueError(str(exc.message)) from exc
```

### Circular Imports Between Job Modules

Avoid direct imports between job modules (`collect_mac_arp.py` to `collect_topology.py`). If a function is shared, extract it into the base module (`_base.py`) or a utility module (`utils.py`):

```python
# BAD — potential circular import
# collect_mac_arp.py
from nautobot_netdb_tracking.jobs.collect_topology import normalize_interface_name

# GOOD — shared function in _base.py or utils.py
# jobs/_base.py or jobs/utils.py
def normalize_interface_name(interface: str) -> str:
    ...

# collect_mac_arp.py
from nautobot_netdb_tracking.jobs._base import normalize_interface_name

# collect_topology.py
from nautobot_netdb_tracking.jobs._base import normalize_interface_name
```

### Exception Handling: Never Use Bare `except Exception`

Never silently swallow exceptions. Always log before `continue` or `pass`:

```python
# BAD — exception silently swallowed
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    pass  # We will never know why it failed

# GOOD — log the error, then continue
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    host.logger.warning("MAC collection subtask failed", exc_info=True)
```

### % Formatting: Use f-strings or .format()

Ruff UP031 flags the use of `%` for string formatting (outside `logger.*`). Use f-strings:

```python
# BAD — UP031
summary = "Job completed in %.1fs. Devices: %d success" % (elapsed, count)

# GOOD
summary = f"Job completed in {elapsed:.1f}s. Devices: {count} success"
```

**Exception**: `logger.info("...", arg1, arg2)` calls should keep lazy formatting with `%s`/`%d` (this is the standard Python logging pattern that avoids formatting if the log level is disabled).

---

## Configuration and Packaging

### Dead Dependencies in pyproject.toml

Remove any dependency that is no longer imported in the code. Unnecessary dependencies:

- Increase installation time
- Create false positives in security audits (CVE on an unused package)
- Confuse contributors about the tech stack

Verify with:

```bash
# List all declared dependencies
grep -E '^\w+ = ' pyproject.toml | awk -F' ' '{print $1}'

# Check if each package is imported somewhere
rg 'import tenacity|from tenacity' nautobot_netdb_tracking/
rg 'import macaddress|from macaddress' nautobot_netdb_tracking/
```

### Black + Ruff: Use a Single Formatter

Configuring both Black **and** Ruff as formatters creates potential conflicts and confusion. Choose one tool. Ruff is the current standard (faster, includes formatting + linting):

```toml
# BAD — two formatters configured in pyproject.toml
[tool.black]
line-length = 120

[tool.ruff]
line-length = 120

# GOOD — ruff only
[tool.ruff]
line-length = 120
```

If Black is kept for compatibility, ensure both configs are strictly identical (`line-length`, `target-version`).

### URLs in pyproject.toml

The `homepage`, `repository`, and `documentation` fields in pyproject.toml must point to URLs that actually exist. Invalid URLs break links on PyPI and confuse users:

```toml
# BAD — URLs that do not exist
homepage = "https://github.com/networktocode/nautobot-netdb-tracking"
documentation = "https://docs.nautobot.com/projects/netdb-tracking/"

# GOOD — real URLs or omit them
homepage = "https://github.com/tcheval/nautobot-netdb-tracking"
repository = "https://github.com/tcheval/nautobot-netdb-tracking"
```

### CI: Never Comment Out the Test Job

The test job in `.github/workflows/ci.yml` must **never** be commented out. A CI without tests is a false sense of security. If tests fail, fix them — do not disable the job.

---

## FakeNOS and Integration Tests

### Critical Limitation

NAPALM getters "succeed" on FakeNOS but return **inconsistent data** (wrong MACs, wrong interfaces, VLAN 666). The Netmiko/TextFSM fallback never triggers because NAPALM does not raise an exception.

### Absolute Rule

**NEVER** modify production code to work around FakeNOS limitations. Fix the test infrastructure instead:

- Configure FakeNOS responses to return realistic data
- Mock NAPALM getters in unit tests
- Reserve FakeNOS for connectivity tests, not parsing tests

### TextFSM: destination_port Is a List

The `destination_port` field in the Cisco IOS MAC table TextFSM template returns a **list** (`['Gi1/0/1']`), not a string. The code handles this correctly:

```python
interface = entry.get("destination_port") or entry.get("interface") or ""
if isinstance(interface, list):
    interface = interface[0] if interface else ""
```

### FakeNOS and get_interfaces

`get_interfaces` works on FakeNOS (returns data), unlike the other MAC/ARP getters. But the returned interface names may not match those in Nautobot (e.g., paris-rtr -- 16 interfaces collected, 0 matched).

---

## Nautobot Status - Semantic Pitfalls

### Never Use a Semantically Incorrect Status as Fallback

The default statuses for `dcim.interface` are: **Active, Decommissioning, Failed, Maintenance, Planned**. None of them corresponds to "interface operationally down".

```python
# DON'T — "Planned" means "not yet deployed", not "oper-down"
status_inactive = interface_statuses.filter(name="Planned").first()
status_inactive_obj = interface_statuses.filter(name="Inactive").first()
if status_inactive_obj:
    status_inactive = status_inactive_obj
# If "Inactive" does not exist → fallback to "Planned" → BUG

# DO — if the status does not exist, do not change it
status_down = interface_statuses.filter(name="Down").first()
# status_down can be None → the condition short-circuits → no change
if not is_up and status_down and nb_interface.status == status_active:
    nb_interface.status = status_down
```

### The "Down" Status Exists but Not for Interfaces

The "Down" status is pre-installed in Nautobot but only for `ipam.vrf` and `vpn.vpntunnel`. To use it on interfaces:

```bash
# Add dcim.interface to the "Down" status content types
curl -X PATCH -H 'Authorization: Token ...' -H 'Content-Type: application/json' \
  -d '{"content_types":["ipam.vrf","vpn.vpntunnel","dcim.interface"]}' \
  'http://localhost:8080/api/extras/statuses/<down-status-uuid>/'
```

---

## Docker - Hot Deployment of the Plugin

### Correct Sequence (CRITICAL)

`pip install --upgrade` is a **no-op** if the version has not changed. The Celery worker keeps the old code in memory even after `pip install`.

```bash
# DON'T — does not reinstall if same version, old /tmp/ is stale
docker cp ./plugin container:/tmp/plugin
docker exec container pip install --upgrade /tmp/plugin
docker restart container

# DO — rm, cp fresh, force-reinstall, restart, verify
for c in nautobot nautobot-worker nautobot-scheduler; do
  docker exec $c rm -rf /tmp/nautobot_netdb_tracking
  docker cp ./nautobot_netdb_tracking $c:/tmp/nautobot_netdb_tracking
  docker exec $c pip install --force-reinstall --no-deps /tmp/nautobot_netdb_tracking
done
docker restart nautobot nautobot-worker nautobot-scheduler

# Verify that the installed code is correct
docker exec nautobot-worker grep "status_down" \
  /usr/local/lib/python3.12/site-packages/nautobot_netdb_tracking/jobs/collect_mac_arp.py
```

### Why `--force-reinstall --no-deps`

- `--force-reinstall`: forces pip to reinstall even if the version is identical
- `--no-deps`: avoids reinstalling all dependencies (much faster)
- Without these flags, pip compares the version number and skips the installation

---

## Pre-commit Checklist

### Linting and Formatting

1. `ruff check` — zero new errors
2. `ruff format --check` — zero new files to reformat

### Models and ORM

1. No `.save()` — always `validated_save()`
2. No query inside a loop — `select_related` / `prefetch_related`
3. Every `Cable()` has a `status=` (retrieved via `Status.objects.get_for_model(Cable)`)
4. `UniqueConstraint` names use the `%(app_label)s_%(class)s_` prefix
5. No separate `count()` + `delete()` — use the return value of `delete()`

### Views and API

1. Custom views (`View`) have `LoginRequiredMixin` + `PermissionRequiredMixin`
2. Each `permission_required` corresponds to the displayed model (not a generic permission)
3. API ViewSets have all serializer FK fields in `select_related()`
4. No dead serializer/code — remove anything that is not imported

### Jobs and Signals

1. `post_migrate.connect()` has a `sender=` to prevent multiple executions
2. No unnecessary dependency in `pyproject.toml` — verify imports

### Tests

1. Fixtures use `validated_save()`, not `.create()` or `.save()`
2. FK filter tests use lists: `[str(device.pk)]`
3. No `.configure(request)` on tables
4. The CI test job is NOT commented out

### Nornir

1. `NornirSubTaskError.result` is a `MultiResult` (list) — iterate to extract the root cause
2. Do not raise `RuntimeError` on partial failure — only if `devices_success == 0`

### Python

1. One normalization function per concept (DRY) — source of truth in `models.py`
2. No circular imports between job modules — share via `_base.py` or `utils.py`
3. No bare `except Exception: pass` — always log before continuing
4. No `%` formatting in strings (outside `logger.*`) — use f-strings

### Status and Transitions

1. Never use a semantically incorrect status as fallback (e.g., "Planned" for oper-down)
2. If a target status does not exist, **skip the transition** (`None` causes the condition to short-circuit)
3. Verify that the status exists for the correct content type (`dcim.interface`, not just `ipam.vrf`)

### Docker Deployment

1. `pip install --upgrade` does not reinstall if same version — use `--force-reinstall --no-deps`
2. Always `rm -rf /tmp/old` before `docker cp` fresh — the old `/tmp/` is stale
3. Always verify the installed code with `grep` after deploy — the worker may keep the old code in memory
