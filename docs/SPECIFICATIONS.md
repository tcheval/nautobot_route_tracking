# Technical Specifications -- nautobot_route_tracking

**Version**: 0.1.0
**Date**: 2026-02-18
**Status**: Approved

---

## 1. Data Model -- `RouteEntry`

### Inheritance

```python
from nautobot.apps.models import PrimaryModel

class RouteEntry(PrimaryModel):
```

`PrimaryModel` provides: `id` (UUID PK), `created`, `last_updated`, `_custom_field_data`, `tags`, Nautobot mixins.

### Inner class `Protocol`

```python
class Protocol(models.TextChoices):
    OSPF = "ospf", "OSPF"
    BGP = "bgp", "BGP"
    STATIC = "static", "Static"
    CONNECTED = "connected", "Connected"
    ISIS = "isis", "IS-IS"
    RIP = "rip", "RIP"
    EIGRP = "eigrp", "EIGRP"
    LOCAL = "local", "Local"
    UNKNOWN = "unknown", "Unknown"
```

Values are stored in the database in **lowercase** (normalized from NAPALM which returns uppercase).

### Fields

| Field | Exact Django type | Options | Notes |
| ----- | ----------------- | ------- | ----- |
| `device` | `ForeignKey("dcim.Device")` | `on_delete=CASCADE`, `related_name="route_entries"` | Required |
| `vrf` | `ForeignKey("ipam.VRF")` | `on_delete=SET_NULL`, `null=True`, `blank=True`, `related_name="route_entries"` | `NULL` = global table |
| `network` | `CharField(max_length=50)` | -- | E.g., `"10.0.0.0/8"` |
| `prefix_length` | `PositiveSmallIntegerField()` | -- | Extracted from `network` in `clean()` |
| `protocol` | `CharField(max_length=20, choices=Protocol.choices)` | -- | Stored lowercase |
| `next_hop` | `CharField(max_length=50, blank=True)` | `default=""` | Empty for CONNECTED routes |
| `outgoing_interface` | `ForeignKey("dcim.Interface")` | `on_delete=SET_NULL`, `null=True`, `blank=True`, `related_name="route_entries"` | Optional |
| `metric` | `PositiveIntegerField(default=0)` | -- | Route cost |
| `admin_distance` | `PositiveSmallIntegerField(default=0)` | -- | NAPALM `preference` field |
| `is_active` | `BooleanField(default=True)` | -- | NAPALM `current_active` field |
| `routing_table` | `CharField(max_length=100, default="default")` | -- | Raw VRF name from NAPALM (e.g., `"inet.0"` on JunOS) |
| `first_seen` | `DateTimeField(auto_now_add=True)` | -- | Managed automatically |
| `last_seen` | `DateTimeField()` | -- | Managed manually in `update_or_create_entry()` |

### `natural_key_field_lookups`

```python
natural_key_field_lookups = ["device__name", "network", "next_hop", "protocol"]
```

### Meta class

```python
class Meta:
    verbose_name = "Route Entry"
    verbose_name_plural = "Route Entries"
    ordering = ["-last_seen"]
    constraints = [
        models.UniqueConstraint(
            fields=["device", "vrf", "network", "next_hop", "protocol"],
            name="nautobot_route_tracking_routeentry_unique_route",
        ),
        # PostgreSQL treats NULL as distinct in UNIQUE constraints, so
        # vrf=NULL rows are not protected by the constraint above.
        models.UniqueConstraint(
            fields=["device", "network", "next_hop", "protocol"],
            condition=models.Q(vrf__isnull=True),
            name="nautobot_route_tracking_routeentry_unique_route_no_vrf",
        ),
    ]
    indexes = [
        models.Index(fields=["device", "last_seen"], name="idx_route_device_lastseen"),
        models.Index(fields=["network", "last_seen"], name="idx_route_network_lastseen"),
        models.Index(fields=["protocol", "last_seen"], name="idx_route_protocol_lastseen"),
        models.Index(fields=["last_seen"], name="idx_route_lastseen"),
        models.Index(fields=["first_seen"], name="idx_route_firstseen"),
    ]
```

**UniqueConstraint note**: PostgreSQL treats `NULL` as distinct in UNIQUE constraints -- the primary constraint does not protect `vrf=NULL` rows. The partial index `unique_route_no_vrf` covers this case. `select_for_update()` is used in `update_or_create_entry()` to prevent TOCTOU race conditions.

### `clean()`

```python
def clean(self) -> None:
    super().clean()

    # Validate that outgoing_interface belongs to the device
    if self.outgoing_interface and self.device:
        if self.outgoing_interface.device_id != self.device_id:
            raise ValidationError(
                {"outgoing_interface": "Interface must belong to the specified device"}
            )

    # Extract prefix_length from network
    if self.network and "/" in self.network:
        try:
            self.prefix_length = int(self.network.split("/")[1])
        except (ValueError, IndexError):
            raise ValidationError({"network": f"Invalid network format: {self.network}"})

    # Initialize last_seen if not provided
    if not self.last_seen:
        self.last_seen = timezone.now()
```

### `__str__()`

```python
def __str__(self) -> str:
    vrf_str = f" [{self.vrf.name}]" if self.vrf else ""
    via_str = f" via {self.next_hop}" if self.next_hop else ""
    return f"{self.device.name}: {self.network}{via_str} ({self.protocol}){vrf_str}"
```

### `update_or_create_entry()` -- CRITICAL NetDB Pattern

```python
@classmethod
def update_or_create_entry(
    cls,
    device: Device,
    network: str,
    protocol: str,
    vrf: VRF | None = None,
    next_hop: str = "",
    **kwargs: Any,
) -> tuple["RouteEntry", bool]:
    """Apply NetDB UPDATE vs INSERT logic for a route.

    Args:
        device: Nautobot Device instance
        network: Network prefix (e.g., "10.0.0.0/8")
        protocol: Routing protocol (lowercase, e.g., "ospf")
        vrf: Optional VRF instance (None = global table)
        next_hop: Next-hop IP address (empty for connected routes)
        **kwargs: Additional fields to set (metric, admin_distance, is_active,
                  outgoing_interface, routing_table)

    Returns:
        Tuple of (entry, created) where created=True if INSERT, False if UPDATE

    """
    with transaction.atomic():
        existing = cls.objects.select_for_update().filter(
            device=device,
            vrf=vrf,
            network=network,
            next_hop=next_hop,
            protocol=protocol,
        ).first()

        if existing:
            # UPDATE: refresh last_seen + volatile fields
            existing.last_seen = timezone.now()
            for field, value in kwargs.items():
                setattr(existing, field, value)
            existing.validated_save()
            return existing, False

        # INSERT: new route or changed path
        entry = cls(
            device=device,
            vrf=vrf,
            network=network,
            next_hop=next_hop,
            protocol=protocol,
            last_seen=timezone.now(),
            **kwargs,
        )
        entry.validated_save()
        return entry, True
```

---

## 2. Collection Strategy

### Primary Method -- NAPALM CLI (platform-specific)

Collection uses `napalm_cli` with platform-specific commands:

- **Arista EOS**: `show ip route | json` -- structured JSON, parsed directly by `_parse_eos_routes()`
- **Cisco IOS**: `show ip route` -- text output, parsed via TextFSM (`ntc-templates`, template `cisco_ios_show_ip_route`)

```python
# EOS
sub_result = task.run(task=napalm_cli, commands=["show ip route | json"], severity_level=logging.DEBUG)
routes = _parse_eos_routes(sub_result[0].result["show ip route | json"])

# IOS
sub_result = task.run(task=napalm_cli, commands=["show ip route"], severity_level=logging.DEBUG)
routes = _parse_ios_routes(sub_result[0].result["show ip route"])
```

**No fallback**: unsupported platforms result in `Result(failed=True)` + device skipped.

### Protocol Normalization

EOS returns specific `routeType` values (e.g., `"eBGP"`, `"ospfExt1"`, `"ospfIntra"`) normalized via `_EOS_PROTOCOL_MAP`. IOS returns single-letter codes (e.g., `"O"`, `"B"`, `"S"`) normalized via `_IOS_PROTOCOL_MAP`.

```python
# EOS: _EOS_PROTOCOL_MAP
"ebgp" -> "bgp", "ibgp" -> "bgp", "ospfinter" -> "ospf", "ospfext1" -> "ospf", etc.

# IOS: _IOS_PROTOCOL_MAP
"O" -> "ospf", "B" -> "bgp", "S" -> "static", "C" -> "connected", etc.
```

### ECMP Handling

Each next-hop in the list becomes a separate `RouteEntry` row:

```python
for prefix, nexthops in routes.items():
    for nexthop in nexthops:   # ECMP: can have multiple next-hops
        process_single_route(device, prefix, nexthop)
```

### Empty next_hop Handling

CONNECTED and LOCAL routes often return `next_hop=""` in NAPALM (Arista EOS in particular). The empty string is stored as-is.

### Excluded Prefixes

```python
EXCLUDED_ROUTE_NETWORKS: tuple[str, ...] = (
    "224.0.0.0/4",     # IPv4 Multicast (includes 239.0.0.0/8)
    "169.254.0.0/16",  # IPv4 Link-local
    "127.0.0.0/8",     # IPv4 Loopback
    "ff00::/8",        # IPv6 Multicast
    "fe80::/10",       # IPv6 Link-local
    "::1/128",         # IPv6 Loopback
)
```

Filtering uses `ipaddress.ip_network().subnet_of()` with IP version checking (IPv4 vs IPv6).

### VRF Resolution

```python
routing_table = nexthop.get("routing_table", "default")

if routing_table and routing_table not in ("default", "inet.0", ""):
    vrf = VRF.objects.filter(name=routing_table).first()
else:
    vrf = None  # Global table
```

### `outgoing_interface` Resolution

```python
iface_name = nexthop.get("outgoing_interface", "")
interface = None
if iface_name:
    interface = interfaces_by_name.get(iface_name)
    if not interface:
        interface = interfaces_by_name.get(normalize_interface_name(iface_name))
```

Pre-fetched before the loop: `interfaces_by_name = {i.name: i for i in Interface.objects.filter(device=device)}`.

---

## 3. NetDB UPDATE/INSERT Logic -- Algorithmic Summary

```text
For each route collected from a device:
  1. Normalize protocol to lowercase
  2. Check if prefix is excluded (multicast, link-local) -> skip
  3. For each next-hop (ECMP):
     a. Resolve VRF (None if global table)
     b. Resolve outgoing_interface (None if not found)
     c. Query: RouteEntry.filter(device, vrf, network, next_hop, protocol).first()
     d. If found -> UPDATE last_seen + volatile fields (metric, admin_distance, is_active)
     e. If not found -> INSERT new entry (first_seen = auto, last_seen = now)

Result:
  - Route stable for 90 days -> 1 single record (original first_seen, last_seen = last scan)
  - Route changes next-hop -> new INSERT entry (old next-hop expires)
  - ECMP route (2 next-hops) -> 2 distinct entries
```

---

## 4. Jobs

### `CollectRoutesJob(BaseCollectionJob)`

**Meta**:

```python
class Meta:
    name = "Collect Route Tables"
    grouping = "Route Tracking"
    description = "Collect routing table entries from network devices via NAPALM CLI"
    has_sensitive_variables = False
    soft_time_limit = 3600
    time_limit = 7200
```

**Variables** (inherited from `BaseCollectionJob`):

- `dynamic_group`, `device`, `device_role`, `location`, `tag` (filters)
- `workers` (IntegerVar, default=50, min=1, max=100)
- `timeout` (IntegerVar, default=30, min=10, max=300)
- `commit` (BooleanVar, default=True)
- `debug_mode` (BooleanVar, default=False)

**`run()` workflow**:

1. `get_target_devices(device, dynamic_group, device_role, location, tag)`
2. `initialize_nornir(devices, workers, timeout)`
3. `nr.run(task=collect_routes_task)` -- **SINGLE parallel call**
4. For each device (sequential):
   - Check `host_result.failed`
   - If `commit`: `process_routes(device, routes_data)` -> stats
   - Otherwise: log DRY-RUN counts
5. Log summary
6. `RuntimeError` if `devices_success == 0 AND devices_failed > 0`

**`_collect_routes_task(task)`** -- dispatches by platform:

```python
def _collect_routes_task(task: Task) -> Result:
    platform = task.host.platform or ""
    if platform == "arista_eos":
        return _collect_routes_eos(task)   # show ip route | json
    elif platform == "cisco_ios":
        return _collect_routes_ios(task)   # show ip route + TextFSM
    else:
        return Result(host=task.host, failed=True,
                      result=f"Unsupported platform: {platform!r}")
```

**`process_routes(device, routes_dict)`**:

```python
def process_routes(self, device: Device, routes_dict: dict) -> dict[str, int]:
    stats = {"updated": 0, "created": 0, "errors": 0, "skipped": 0}

    # Pre-fetch interfaces
    interfaces_by_name = {i.name: i for i in Interface.objects.filter(device=device)}

    with transaction.atomic():
        for prefix, nexthops in routes_dict.items():
            for nexthop_data in nexthops:
                try:
                    if _is_excluded_network(prefix):
                        stats["skipped"] += 1
                        continue

                    protocol = nexthop_data.get("protocol", "unknown").lower()
                    next_hop = nexthop_data.get("next_hop", "")
                    routing_table = nexthop_data.get("routing_table", "default")
                    metric = nexthop_data.get("preference", 0) or 0
                    admin_distance = nexthop_data.get("preference", 0) or 0
                    is_active = nexthop_data.get("current_active", True)
                    iface_name = nexthop_data.get("outgoing_interface", "")

                    # Resolve VRF
                    vrf = _resolve_vrf(routing_table)

                    # Resolve interface
                    interface = interfaces_by_name.get(iface_name)
                    if not interface and iface_name:
                        interface = interfaces_by_name.get(normalize_interface_name(iface_name))

                    _, created = RouteEntry.update_or_create_entry(
                        device=device,
                        network=prefix,
                        protocol=protocol,
                        vrf=vrf,
                        next_hop=next_hop,
                        outgoing_interface=interface,
                        metric=metric,
                        admin_distance=admin_distance,
                        is_active=is_active,
                        routing_table=routing_table,
                    )
                    stats["created" if created else "updated"] += 1

                except Exception as e:
                    stats["errors"] += 1
                    self.logger.error(
                        "Error processing route %s: %s", prefix, e,
                        extra={"grouping": device.name},
                    )

    return stats
```

### `PurgeOldRoutesJob(Job)`

**Meta**: `name = "Purge Old Routes"`, `grouping = "Route Tracking"`

**Variables**:

- `retention_days`: IntegerVar(default=90, min_value=1, max_value=365)
- `commit`: BooleanVar(default=True)

**`run()`**:

```python
def run(self, *, retention_days: int, commit: bool) -> dict[str, int]:
    cutoff_date = timezone.now() - timedelta(days=retention_days)

    if commit:
        with transaction.atomic():
            count, _ = RouteEntry.objects.filter(last_seen__lt=cutoff_date).delete()
    else:
        count = RouteEntry.objects.filter(last_seen__lt=cutoff_date).count()

    mode = "Purged" if commit else "Would purge"
    self.logger.info(
        "%s %d route entries older than %d days",
        mode, count, retention_days,
        extra={"grouping": "summary"},
    )
    return {"route_entries": count}
```

---

## 5. UI / API

### `RouteEntryFilterSet(NautobotFilterSet)`

```python
class RouteEntryFilterSet(NautobotFilterSet):
    q = SearchFilter(
        filter_predicates={
            "device__name": "icontains",
            "network": "icontains",
            "next_hop": "icontains",
            "vrf__name": "icontains",
        }
    )
    device = NaturalKeyOrPKMultipleChoiceFilter(queryset=Device.objects.all(), to_field_name="name")
    vrf = NaturalKeyOrPKMultipleChoiceFilter(queryset=VRF.objects.all(), to_field_name="name")
    protocol = django_filters.MultipleChoiceFilter(choices=RouteEntry.Protocol.choices)
    network = django_filters.CharFilter(lookup_expr="icontains")
    next_hop = django_filters.CharFilter(lookup_expr="icontains")
    last_seen_after = django_filters.DateTimeFilter(field_name="last_seen", lookup_expr="gte")
    last_seen_before = django_filters.DateTimeFilter(field_name="last_seen", lookup_expr="lte")

    class Meta:
        model = RouteEntry
        fields = ["id", "device", "vrf", "protocol", "network", "next_hop",
                  "last_seen_after", "last_seen_before"]
```

**Critical input format** (for tests):

```python
# FK -> list of strings
filterset = RouteEntryFilterSet({"device": [str(device.pk)]})
filterset = RouteEntryFilterSet({"vrf": [str(vrf.pk)]})
# MultipleChoiceFilter -> list of strings
filterset = RouteEntryFilterSet({"protocol": ["ospf", "bgp"]})
# CharFilter -> bare string
filterset = RouteEntryFilterSet({"network": "10.0"})
```

### `RouteEntryTable(BaseTable)`

```python
class RouteEntryTable(BaseTable):
    pk = ToggleColumn()
    device = tables.Column(linkify=True)
    vrf = tables.Column(linkify=True)
    network = tables.Column()
    protocol = tables.Column()
    next_hop = tables.Column()
    outgoing_interface = tables.Column(linkify=True)
    metric = tables.Column()
    admin_distance = tables.Column()
    is_active = tables.BooleanColumn()
    first_seen = tables.DateTimeColumn(format="Y-m-d H:i")
    last_seen = tables.DateTimeColumn(format="Y-m-d H:i")
    actions = ButtonsColumn(RouteEntry)

    class Meta:
        model = RouteEntry
        fields = ("pk", "device", "vrf", "network", "protocol", "next_hop",
                  "outgoing_interface", "metric", "admin_distance", "is_active",
                  "first_seen", "last_seen", "actions")
        default_columns = ("pk", "device", "vrf", "network", "protocol", "next_hop",
                           "is_active", "last_seen", "actions")
```

### `RouteEntryUIViewSet(NautobotUIViewSet)`

```python
class RouteEntryUIViewSet(NautobotUIViewSet):
    queryset = RouteEntry.objects.select_related(
        "device", "device__location", "vrf", "outgoing_interface"
    ).prefetch_related("tags")
    filterset_class = RouteEntryFilterSet
    table_class = RouteEntryTable
    action_buttons = ("export",)
```

### REST API (read-only)

```python
# api/serializers.py
class RouteEntrySerializer(NautobotModelSerializer):
    # NautobotModelSerializer handles FK nesting automatically (Nautobot 3.x
    # removed all Nested*Serializer classes -- NestedDeviceSerializer, etc.
    # no longer exist).
    class Meta:
        model = RouteEntry
        fields = [...]  # all fields
        read_only_fields = ["first_seen", "last_seen", "created", "last_updated"]

# api/views.py -- read-only (writes bypass NetDB logic)
class RouteEntryViewSet(NautobotModelViewSet):
    http_method_names = ["get", "head", "options"]
    queryset = RouteEntry.objects.select_related(
        "device", "vrf", "outgoing_interface"
    ).prefetch_related("tags")
    serializer_class = RouteEntrySerializer
    filterset_class = RouteEntryFilterSet
```

Endpoints (read-only):

- `GET /api/plugins/route-tracking/routes/` -- paginated list
- `GET /api/plugins/route-tracking/routes/<uuid>/` -- detail

### Device tab -- `template_content.py`

```python
from nautobot.apps.ui import TemplateExtension

class DeviceRoutesTab(TemplateExtension):
    model = "dcim.device"

    def detail_tabs(self):
        return [
            {
                "title": "Routes",
                "url": reverse(
                    "plugins:nautobot_route_tracking:routeentry_list",
                ) + f"?device={self.context['object'].pk}",
            }
        ]

template_extensions = [DeviceRoutesTab]
```

---

## 6. Testing Strategy

### `tests/conftest.py` -- Fixtures

```python
@pytest.fixture
def device(db):
    return DeviceFactory()

@pytest.fixture
def vrf(db):
    return VRFFactory()

@pytest.fixture
def interface(db, device):
    return InterfaceFactory(device=device)

@pytest.fixture
def route_entry(db, device, vrf, interface):
    return RouteEntryFactory(device=device, vrf=vrf, outgoing_interface=interface)
```

### `tests/factories.py`

```python
class RouteEntryFactory(DjangoModelFactory):
    device = SubFactory(DeviceFactory)
    vrf = None
    network = Sequence(lambda n: f"10.{n}.0.0/24")
    prefix_length = 24
    protocol = RouteEntry.Protocol.OSPF
    next_hop = Sequence(lambda n: f"192.168.1.{n}")
    metric = 110
    admin_distance = 110
    is_active = True
    last_seen = factory.LazyFunction(timezone.now)

    class Meta:
        model = RouteEntry
```

### Priority Tests

| File | Key tests |
| ---- | --------- |
| `test_models.py` | creation, UniqueConstraint IntegrityError, clean() ValidationError, `__str__()`, UPDATE vs INSERT (update_or_create_entry) |
| `test_jobs.py` | UPDATE last_seen, INSERT new route, ECMP (2 next-hops = 2 rows), excluded prefix skipped, PurgeOldRoutesJob |
| `test_filters.py` | device (list[str]), vrf (list[str]), protocol (list), network (icontains), q |
| `test_api.py` | GET list/detail, POST, PATCH, DELETE, unauthorized -> 403 |
| `test_views.py` | list 200, detail 200, permissions |

### Mock pattern for jobs

```python
from unittest.mock import patch, MagicMock

@patch("nautobot_route_tracking.jobs.collect_routes.InitNornir")
def test_collect_routes_update_logic(mock_nornir, db, device):
    mock_result = MagicMock()
    mock_result.failed = False
    mock_result.result = {
        "10.0.0.0/8": [
            {"protocol": "OSPF", "next_hop": "192.168.1.1", "current_active": True,
             "preference": 110, "routing_table": "default", "outgoing_interface": ""}
        ]
    }
    mock_nornir.return_value.run.return_value = {device.name: mock_result}
    ...
```

---

## 7. Performance

| Parameter | Default value | Configurable |
| --------- | ------------- | ------------ |
| Nornir workers | 50 | Yes (1-100) |
| Timeout per device | 30s | Yes (10-300s) |
| Pre-fetch interfaces | Per device before loop | No (automatic) |
| Pre-fetch VRFs | At job startup | No (automatic) |
| transaction.atomic() | Per device | No (automatic) |

Database optimizations:

- `select_related("device", "vrf", "outgoing_interface")` on all UI/API querysets
- `prefetch_related("tags")` on all querysets
- Index on `(device, last_seen)`, `(network, last_seen)`, `(protocol, last_seen)`

---

## 8. Plugin Configuration

```python
# nautobot_config.py
PLUGINS = ["nautobot_route_tracking"]
PLUGINS_CONFIG = {
    "nautobot_route_tracking": {
        "retention_days": 90,         # int: default retention in days
        "nornir_workers": 50,         # int: default Nornir workers
        "device_timeout": 30,         # int: timeout per device in seconds
    }
}
```

`default_settings` in `NautobotAppConfig.__init__.py`:

```python
default_settings = {
    "retention_days": 90,
    "nornir_workers": 50,
    "device_timeout": 30,
}
```

---

## 9. Deployment

### Installation

```bash
pip install nautobot-route-tracking
```

### Configuration

Add to `nautobot_config.py`:

```python
PLUGINS = ["nautobot_route_tracking"]
PLUGINS_CONFIG = {"nautobot_route_tracking": {"retention_days": 90}}
```

### Migrations

```bash
nautobot-server migrate
nautobot-server collectstatic --no-input
```

### Restart

```bash
# Docker
docker restart nautobot nautobot-worker nautobot-scheduler

# Docker Compose
docker compose restart nautobot nautobot-worker nautobot-scheduler
```

### Nautobot Prerequisites

- Each device must have a **Platform** with `network_driver` configured (e.g., `cisco_ios`, `arista_eos`)
- Each platform must have `napalm_driver` configured (e.g., `ios`, `eos`)
- Each device must have a **SecretsGroup** with SSH credentials
- The `nautobot-plugin-nornir` plugin must be installed and configured in `PLUGINS`

### Post-installation Verification

```bash
# Verify the plugin is loaded
nautobot-server shell -c "import nautobot_route_tracking; print(nautobot_route_tracking.__version__)"

# Verify migrations
nautobot-server showmigrations nautobot_route_tracking

# Verify jobs
nautobot-server shell -c "from nautobot.extras.models import Job; print(Job.objects.filter(module_name__contains='route_tracking').values('name', 'enabled'))"
```
