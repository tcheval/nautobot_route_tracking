# Jobs Analysis -- nautobot_netdb_tracking

**Files analyzed**: `jobs/__init__.py`, `jobs/_base.py`, `jobs/collect_mac_arp.py`, `jobs/purge_old_data.py`
**Analysis date**: 2026-02-18

---

## 1. `jobs/__init__.py` -- Registration Pattern

```python
from nautobot.core.celery import register_jobs

from nautobot_netdb_tracking.jobs.collect_mac_arp import CollectMACARPJob
from nautobot_netdb_tracking.jobs.collect_topology import CollectTopologyJob
from nautobot_netdb_tracking.jobs.purge_old_data import PurgeOldDataJob

jobs = [CollectMACARPJob, CollectTopologyJob, PurgeOldDataJob]

register_jobs(*jobs)
```

Critical points:

- Import from `nautobot.core.celery` (not `nautobot.apps.jobs`)
- `register_jobs(*jobs)` called at module level (not in `ready()`)
- Without this call, jobs do not appear in the Nautobot UI

---

## 2. `jobs/_base.py` -- `BaseCollectionJob`

### 2.1 Critical Imports

```python
from nautobot.apps.jobs import BooleanVar, IntegerVar, Job, ObjectVar
from nautobot.dcim.models import Device, Location
from nautobot.extras.models import DynamicGroup, Role, Status, Tag
from nornir import InitNornir
from nornir.core.exceptions import NornirSubTaskError
from nornir.core.plugins.inventory import InventoryPluginRegister
```

### 2.2 Constants

```python
SUPPORTED_PLATFORMS: tuple[str, ...] = (
    "cisco_ios", "cisco_xe", "cisco_xr",
    "arista_eos",
    "ios", "iosxr", "eos",  # Napalm/Netmiko driver names
)

INTERFACE_ABBREVIATIONS: dict[str, str] = {
    "Gi": "GigabitEthernet",
    "Fa": "FastEthernet",
    "Te": "TenGigabitEthernet",
    "Twe": "TwentyFiveGigE",
    "Fo": "FortyGigabitEthernet",
    "Hu": "HundredGigE",
    "Eth": "Ethernet",
    "Et": "Ethernet",
    "Po": "Port-channel",
    "Vl": "Vlan",
    "Lo": "Loopback",
    "Tu": "Tunnel",
    "Mg": "Management",
    "mgmt": "Management",
}
```

### 2.3 `_extract_nornir_error()` -- Module-level Function (CRITICAL)

```python
def _extract_nornir_error(exc: NornirSubTaskError) -> str:
    """NornirSubTaskError.result is a MultiResult (list), NOT a single Result."""
    if hasattr(exc, "result"):
        for r in exc.result:
            if r.failed:
                if r.exception:
                    return str(r.exception)
                if r.result:
                    return str(r.result)
    return str(exc)
```

**PITFALL**: `exc.result` is a `MultiResult` (list), not a single object. Never do `exc.result.exception`.

### 2.4 NautobotORMInventory Registration

```python
try:
    from nautobot_plugin_nornir.plugins.inventory.nautobot_orm import NautobotORMInventory
    InventoryPluginRegister.register("nautobot-inventory", NautobotORMInventory)
except ImportError:
    NautobotORMInventory = None
```

Registration at module level (once at import time).

### 2.5 `normalize_interface_name()` -- Module-level Function

```python
def normalize_interface_name(interface: str) -> str:
    """Expand Gi0/1 -> GigabitEthernet0/1"""
    if not interface:
        return interface
    interface = interface.strip()
    # Sorted longest first to avoid partial matches (e.g. "Eth" before "Et")
    for abbrev, full in sorted(INTERFACE_ABBREVIATIONS.items(), key=lambda x: len(x[0]), reverse=True):
        if interface.startswith(abbrev):
            if not interface.startswith(full):
                return full + interface[len(abbrev):]
            return interface
    return interface
```

### 2.6 `BaseCollectionJob` -- Variables

| Variable | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `dynamic_group` | `ObjectVar(DynamicGroup)` | `required=False` | DynamicGroup filter |
| `device` | `ObjectVar(Device)` | `required=False` | Specific device (highest priority) |
| `device_role` | `ObjectVar(Role)` | `required=False` | Filter by role |
| `location` | `ObjectVar(Location)` | `required=False` | Filter by location |
| `tag` | `ObjectVar(Tag)` | `required=False` | Filter by tag |
| `workers` | `IntegerVar` | `50`, min=1, max=100 | Nornir parallel workers |
| `timeout` | `IntegerVar` | `30`, min=10, max=300 | Timeout per device (seconds) |
| `commit` | `BooleanVar` | `True` | Commit changes (False = dry-run) |
| `debug_mode` | `BooleanVar` | `False` | Enable verbose debug logging |

### 2.7 `get_target_devices()` -- Complete Logic

```python
def get_target_devices(self, device, dynamic_group, device_role, location, tag) -> QuerySet[Device]:
    # Priority 1: Specific device
    if device:
        return Device.objects.filter(pk=device.pk)

    # Base queryset: Active|Staged + has platform
    active_statuses = Status.objects.get_for_model(Device).filter(name__in=["Active", "Staged"])
    queryset = Device.objects.filter(
        status__in=active_statuses,
        platform__isnull=False,
    ).select_related("platform", "location", "role")

    # Priority 2: DynamicGroup
    if dynamic_group:
        member_ids = dynamic_group.members.values_list("pk", flat=True)
        queryset = queryset.filter(pk__in=member_ids)

    # Priority 3: Manual filters (additive)
    if device_role:
        queryset = queryset.filter(role=device_role)
    if location:
        # IMPORTANT: include child locations
        queryset = queryset.filter(location__in=location.descendants(include_self=True))
    if tag:
        queryset = queryset.filter(tags=tag)

    # Always filter by supported platforms
    queryset = queryset.filter(platform__network_driver__in=SUPPORTED_PLATFORMS)

    return queryset.distinct()
```

**Critical points**:

- `location.descendants(include_self=True)` -> automatically includes child locations
- `SUPPORTED_PLATFORMS` filter always applied last
- `distinct()` to avoid duplicates with M2M tags

### 2.8 `initialize_nornir()` -- Complete Configuration

Configuration flow:

1. Build `napalm_driver_map` and `napalm_args_map` from device platforms
2. Create `inventory_config` with `NautobotORMInventory` + `CredentialsNautobotSecrets` + defaults (timeouts)
3. `InitNornir(runner=threaded, logging, inventory)`
4. **Post-init fix**: for each host, inject `napalm_driver` and merge `napalm_args` into `optional_args`

The post-init fix is necessary because `NautobotORMInventory` sets `host.platform = network_driver` (e.g. `"arista_eos"`) but NAPALM needs `napalm_driver` (e.g. `"eos"`).

```python
for host_name, host in nr.inventory.hosts.items():
    napalm_driver = napalm_driver_map.get(host_name)
    napalm_opts = host.connection_options.get("napalm")
    if napalm_opts is None and napalm_driver:
        from nornir.core.inventory import ConnectionOptions
        napalm_opts = ConnectionOptions(platform=napalm_driver)
        host.connection_options["napalm"] = napalm_opts
    if napalm_opts is not None:
        if napalm_driver:
            napalm_opts.platform = napalm_driver
        plat_args = napalm_args_map.get(host_name, {})
        if plat_args:
            if napalm_opts.extras is None:
                napalm_opts.extras = {}
            opt_args = napalm_opts.extras.setdefault("optional_args", {})
            for key, value in plat_args.items():
                if key not in opt_args:
                    opt_args[key] = value
```

**`RuntimeError`** raised if `devices.exists() == False` or if Nornir init fails.

---

## 3. `jobs/collect_mac_arp.py` -- `CollectMACARPJob`

### 3.1 Specific Constants

```python
EXCLUDED_MAC_PREFIXES: tuple[str, ...] = (
    "00:00:5e:00:01",  # VRRP IPv4
    "00:00:5e:00:02",  # VRRP IPv6
    "00:00:0c:07:ac",  # HSRPv1
    "00:00:0c:9f:f",   # HSRPv2
    "00:07:b4",        # GLBP
    "01:00:5e",        # IPv4 Multicast
    "33:33",           # IPv6 Multicast
    "01:80:c2:00:00",  # STP/LLDP/LACP
    "ff:ff:ff:ff:ff:ff",  # Broadcast
)
```

### 3.2 Meta Class

```python
class Meta:
    name = "Collect MAC and ARP Tables"
    grouping = "NetDB Tracking"
    description = "Collect MAC/ARP tables and interface state from network devices using Nornir"
    has_sensitive_variables = False
    field_order = ["dynamic_group", "device", "device_role", "location", "tag",
                   "collect_mac", "collect_arp", "collect_interfaces", "collect_vlans",
                   "workers", "timeout", "commit", "debug_mode"]
    approval_required = False
    soft_time_limit = 3600   # 1 hour
    time_limit = 7200        # 2 hours
```

### 3.3 Additional Variables (on top of BaseCollectionJob)

| Variable | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `collect_mac` | `BooleanVar` | `True` | Collect MAC tables |
| `collect_arp` | `BooleanVar` | `True` | Collect ARP tables |
| `collect_interfaces` | `BooleanVar` | `True` | Sync interface state |
| `collect_vlans` | `BooleanVar` | `False` | Sync VLAN/switchport mode |

### 3.4 `__init__()` -- Stats Tracking

```python
def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.stats: dict[str, int | list[str]] = {
        "devices_success": 0, "devices_failed": 0, "devices_skipped": 0,
        "mac_updated": 0, "mac_created": 0, "mac_errors": 0,
        "arp_updated": 0, "arp_created": 0, "arp_errors": 0, "arp_skipped_orphan": 0,
        "iface_updated": 0, "iface_errors": 0,
        "vlan_updated": 0, "vlan_skipped": 0, "vlan_errors": 0,
        "errors": [],
    }
```

### 3.5 Collection Tasks (Module-level Nornir Functions)

#### `collect_mac_table_task(task)` -- NAPALM + TextFSM Fallback Pattern

```text
1. Try napalm_get(getters=["get_mac_address_table"])
   -> normalize output: {"interface": str, "mac": str, "vlan": int|None}
   -> filter EXCLUDED_MAC_PREFIXES
   -> return Result(result=[...])

On NornirSubTaskError or Exception:
   -> napalm_failed = True
   -> log warning

2. Determine command by platform:
   - cisco_ios|ios|cisco_xe|arista_eos|eos -> "show mac address-table"
   - cisco_xr|iosxr -> "show mac-address-table"
   - else -> Result(failed=True, ...)

3. netmiko_send_command(command, use_textfsm=True)
   -> handle TextFSM field name variations:
     - interface: destination_port | interface | ports | port
     - mac: destination_address | mac | mac_address
     - vlan: vlan | vlan_id
   -> interface may be a list -> take [0]
   -> parse vlan as int (contextlib.suppress ValueError)
   -> return Result(result=[...])
```

#### `collect_arp_table_task(task)` -- Same Pattern

```text
Platform commands:
  - cisco_ios|ios|cisco_xe -> "show ip arp"
  - cisco_xr|iosxr|arista_eos|eos -> "show arp"

TextFSM field variations:
  - interface: interface | port
  - ip: address | ip | ip_address
  - mac: mac | mac_address | hardware
  - age: age | time (handle "00:01:23" format -> seconds)
```

#### `_combined_collection_task(task, collect_mac, collect_arp, collect_interfaces, collect_vlans)` -- Dispatcher

Runs all subtasks on ONE SSH session. Returns `Result(result={"mac_table": [], "arp_table": [], "interfaces": {}, "vlans": {}, "switchports": {}})`.

### 3.6 `process_mac_results()` -- **CRITICAL NetDB UPDATE/INSERT Logic**

```python
def process_mac_results(self, device: Device, mac_entries: list[dict]) -> dict[str, int]:
    stats = {"updated": 0, "created": 0, "errors": 0}

    # Pre-fetch interfaces (avoid N+1)
    interfaces_by_name = {iface.name: iface for iface in Interface.objects.filter(device=device)}

    # Pre-fetch VLANs
    vlan_ids = {entry["vlan"] for entry in mac_entries if entry.get("vlan") is not None}
    vlans_by_vid = {vlan.vid: vlan for vlan in VLAN.objects.filter(vid__in=vlan_ids)}

    with transaction.atomic():
        for entry in mac_entries:
            try:
                # 1. Find interface (exact then normalized name)
                interface = interfaces_by_name.get(entry["interface"])
                if not interface:
                    interface = interfaces_by_name.get(normalize_interface_name(entry["interface"]))
                if not interface:
                    stats["errors"] += 1
                    continue

                # 2. Find VLAN (optional)
                vlan = vlans_by_vid.get(entry.get("vlan")) if entry.get("vlan") else None

                # 3. Normalize MAC
                mac_normalized = normalize_mac_address(entry["mac"])

                # 4. NetDB UPDATE/INSERT via model classmethod
                _, created = MACAddressHistory.update_or_create_entry(
                    device=device, interface=interface,
                    mac_address=mac_normalized, vlan=vlan,
                )

                if created:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1

            except Exception as e:
                stats["errors"] += 1
                self.logger.error("Error processing MAC %s: %s", entry.get("mac"), e,
                                  extra={"grouping": device.name})

    return stats
```

**Note**: The actual UPDATE/INSERT logic is in `MACAddressHistory.update_or_create_entry()` (model classmethod), not in the job directly.

### 3.7 `process_arp_results()` -- With Orphan Filtering

```python
# 3. Filter orphan ARPs: skip if MAC not observed on any switchport
if known_macs is not None and mac_normalized not in known_macs:
    stats["skipped_orphan"] += 1
    continue
```

Parameter `known_macs: set[str] | None` -- if `None`, no filtering.

### 3.8 `run()` -- 7-Step Workflow

```text
1. get_target_devices(device, dynamic_group, device_role, location, tag)
   -> if 0 devices -> return {success: False, message: "No devices matched"}

2. initialize_nornir(devices, workers, timeout)
   -> if RuntimeError -> return {success: False, error: ...}

3. Build device_map: {device_name: Device} from Nornir inventory
   -> log warning for devices not in inventory (missing credentials)
   -> if device_map empty -> return {success: False, message: "No devices in inventory"}

4. nr.run(task=_combined_collection_task, ...)
   -> SINGLE PARALLEL call for ALL hosts simultaneously
   -> record collection_elapsed time

5. Pass 1: For each device in device_map:
   - host_result = results[device_name]
   - if host_result.failed -> stats["devices_failed"]++; continue
   - if collected_total == 0 -> stats["devices_failed"]++; continue
   - if commit:
     * process_mac_results() -> stats["mac_*"]
     * process_interface_results() -> stats["iface_*"]
     * process_vlan_results() -> stats["vlan_*"]
   - else: log DRY-RUN counts
   - stats["devices_success"]++
   - Cache collected_data for Pass 2

6. Build known_macs set (if collect_arp and commit):
   known_macs = set of MAC addresses seen in last 24h from MACAddressHistory

7. Pass 2: ARP processing (if collect_arp and commit):
   For each device with collected_data:
     process_arp_results(device, arp_entries, known_macs=known_macs)

8. Log summary (grouping="summary")

RuntimeError raised ONLY if devices_success == 0 AND devices_failed > 0
(total failure = ALL devices failed)
```

---

## 4. `jobs/purge_old_data.py` -- `PurgeOldDataJob`

### 4.1 Meta Class

```python
class Meta:
    name = "Purge Old NetDB Data"
    grouping = "NetDB Tracking"
    description = "Remove MAC/ARP/Topology records older than retention period"
    has_sensitive_variables = False
```

### 4.2 Variables

| Variable | Type | Default | Description |
| -------- | ---- | ------- | ----------- |
| `retention_days` | `IntegerVar` | `90`, min=1, max=365 | Delete records older than N days |
| `commit` | `BooleanVar` | `True` | Commit changes |
| `purge_mac` | `BooleanVar` | `True` | Purge MAC History |
| `purge_arp` | `BooleanVar` | `True` | Purge ARP Entries |
| `purge_topology` | `BooleanVar` | `True` | Purge Topology Connections |

### 4.3 `run()` -- Complete Logic

```python
def run(self, *, retention_days, commit, purge_mac, purge_arp, purge_topology):
    job_start = time.monotonic()
    cutoff_date = timezone.now() - timedelta(days=retention_days)

    stats = {"mac_addresses": 0, "arp_entries": 0, "topology_connections": 0}

    if commit:
        with transaction.atomic():
            if purge_mac:
                mac_count, _ = MACAddressHistory.objects.filter(last_seen__lt=cutoff_date).delete()
                stats["mac_addresses"] = mac_count
            if purge_arp:
                arp_count, _ = ARPEntry.objects.filter(last_seen__lt=cutoff_date).delete()
                stats["arp_entries"] = arp_count
            if purge_topology:
                topo_count, _ = TopologyConnection.objects.filter(last_seen__lt=cutoff_date).delete()
                stats["topology_connections"] = topo_count
    else:
        # DRY-RUN: count only
        if purge_mac:
            stats["mac_addresses"] = MACAddressHistory.objects.filter(last_seen__lt=cutoff_date).count()
        if purge_arp:
            stats["arp_entries"] = ARPEntry.objects.filter(last_seen__lt=cutoff_date).count()
        if purge_topology:
            stats["topology_connections"] = TopologyConnection.objects.filter(last_seen__lt=cutoff_date).count()

    # Log summary with time.monotonic()
    job_elapsed = time.monotonic() - job_start
    mode = "Purged" if commit else "Would purge"
    self.logger.info("%s %d records in %.1fs ...", mode, sum(stats.values()), job_elapsed,
                     extra={"grouping": "summary"})

    return stats
```

---

## 5. Nornir Patterns -- Summary

### Inventory Initialization

```python
nr = InitNornir(
    runner={"plugin": "threaded", "options": {"num_workers": workers}},
    logging={"enabled": True, "level": "DEBUG" if debug else "INFO", "to_console": False},
    inventory={
        "plugin": "nautobot-inventory",
        "options": {
            "credentials_class": "nautobot_plugin_nornir.plugins.credentials.nautobot_secrets.CredentialsNautobotSecrets",
            "queryset": devices,
            "defaults": {
                "connection_options": {
                    "netmiko": {"extras": {"timeout": timeout, "fast_cli": True, ...}},
                    "napalm": {"extras": {"timeout": timeout, "optional_args": {"transport": "ssh"}}},
                }
            },
        },
    },
)
```

### Task Execution

```python
# SINGLE parallel run -- all hosts simultaneously
results = nr.run(task=_combined_collection_task, collect_mac=True, collect_arp=True, ...)

# Result access
host_result = results["device_name"]  # AggregatedResult
if host_result.failed:
    ...
data = host_result.result  # dict from Result(result=...)
```

### Error Handling Pattern

```python
try:
    sub_result = task.run(task=some_napalm_task)
    ...
except NornirSubTaskError as exc:
    root_cause = _extract_nornir_error(exc)  # Iterate MultiResult
    ...
except Exception as exc:
    ...
```

---

## 6. Imports to Reproduce in nautobot_route_tracking

```python
# jobs/__init__.py
from nautobot.core.celery import register_jobs

# jobs/base.py
from nautobot.apps.jobs import BooleanVar, IntegerVar, Job, ObjectVar
from nautobot.dcim.models import Device, Location
from nautobot.extras.models import DynamicGroup, Role, Status, Tag
from nornir import InitNornir
from nornir.core.exceptions import NornirSubTaskError
from nornir.core.plugins.inventory import InventoryPluginRegister
from nautobot_plugin_nornir.plugins.inventory.nautobot_orm import NautobotORMInventory

# jobs/collect_routes.py
from nornir.core.task import Result, Task
from nornir_napalm.plugins.tasks import napalm_get
from nornir_netmiko.tasks import netmiko_send_command
from django.db import transaction
from django.utils import timezone
```

---

## 7. Critical Rules to Reproduce

1. `register_jobs(*jobs)` at module level of `jobs/__init__.py`
2. `BaseCollectionJob` inherits from `Job` (not `BaseJob` or other)
3. `class Meta: abstract = True` in `BaseCollectionJob`
4. Variables defined on the **class** (not in `__init__`)
5. `run()` with `*, **kwargs` for required named parameters
6. **A SINGLE** `nr.run()` call -- never a `for device: nr.filter().run()` loop
7. DB writes **sequential** after the parallel nr.run()
8. `RuntimeError` raised ONLY if `devices_success == 0 AND devices_failed > 0`
9. `validated_save()` everywhere (never `.save()`)
10. `transaction.atomic()` around all batch DB operations
11. `try/except Exception as e` per device -- never let it crash
12. Structured logging: `extra={"grouping": device.name}` per device, `extra={"grouping": "summary"}` at the end
