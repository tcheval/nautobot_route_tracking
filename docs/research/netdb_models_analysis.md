# Models Analysis -- nautobot_netdb_tracking

**Source file analyzed**: `nautobot_netdb_tracking/nautobot_netdb_tracking/models.py`
**Migrations analyzed**: `0001_initial.py`, `0002_rename_constraints.py`, `0003_add_first_seen_indexes.py`
**Analysis date**: 2026-02-18

---

## 1. Overview

The plugin exposes **3 main models**, all inheriting from `PrimaryModel` (Nautobot class):

| Model | DB Table (inferred) | Role |
| ----- | ------------------- | ---- |
| `MACAddressHistory` | `nautobot_netdb_tracking_macaddresshistory` | History of MAC addresses seen on interfaces |
| `ARPEntry` | `nautobot_netdb_tracking_arpentry` | ARP entries collected from devices |
| `TopologyConnection` | `nautobot_netdb_tracking_topologyconnection` | CDP/LLDP connections discovered between devices |

A **module-level helper** is also defined: `normalize_mac_address()`.

---

## 2. Imports in models.py

```python
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from nautobot.apps.models import PrimaryModel
from nautobot.dcim.models import Cable, Device, Interface
from nautobot.extras.models import Status
from nautobot.ipam.models import VLAN, IPAddress, Prefix
```

Notable points:

- `PrimaryModel` comes from `nautobot.apps.models` (not `nautobot.core.models`)
- `transaction` is imported for `transaction.atomic()` in `update_or_create_entry` methods
- `timezone` is used for `timezone.now()` in `clean()` and `update_or_create_entry()`
- All FKs point to Nautobot core models: `Device`, `Interface`, `Cable`, `VLAN`, `IPAddress`, `Prefix`, `Status`

---

## 3. Helper function: `normalize_mac_address()`

```python
def normalize_mac_address(mac: str) -> str:
    if not mac:
        raise ValidationError("MAC address cannot be empty")
    clean_mac = mac.upper().replace(":", "").replace("-", "").replace(".", "")
    if len(clean_mac) != 12 or not all(c in "0123456789ABCDEF" for c in clean_mac):
        raise ValidationError(f"Invalid MAC address format: {mac}")
    return ":".join(clean_mac[i : i + 2] for i in range(0, 12, 2))
```

- Accepts `:`, `-`, `.` or no separator; converts to UPPERCASE
- Produces the format `XX:XX:XX:XX:XX:XX` (17 characters)
- Raises `ValidationError` if empty or invalid format (length != 12 or non-hex characters)

---

## 4. Model: `MACAddressHistory`

### 4.1 Inheritance

```python
class MACAddressHistory(PrimaryModel):
```

`PrimaryModel` automatically provides (confirmed via `0001_initial.py`):

- `id`: `UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)`
- `created`: `DateTimeField(auto_now_add=True, null=True)`
- `last_updated`: `DateTimeField(auto_now=True, null=True)`
- `_custom_field_data`: `JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)`
- `tags`: `TagsField(through='extras.TaggedItem', to='extras.Tag')`
- Mixins: `DataComplianceModelMixin`, `DynamicGroupMixin`, `NotesMixin`

### 4.2 Fields

| Field | Exact Django Type | Options | Notes |
| ----- | ----------------- | ------- | ----- |
| `device` | `ForeignKey(to=Device, ...)` | `on_delete=CASCADE`, `related_name="mac_address_history"` | Required |
| `interface` | `ForeignKey(to=Interface, ...)` | `on_delete=CASCADE`, `related_name="mac_address_history"` | Required |
| `mac_address` | `CharField(max_length=17)` | -- | Format `XX:XX:XX:XX:XX:XX` |
| `vlan` | `ForeignKey(to=VLAN, ...)` | `on_delete=SET_NULL`, `related_name="mac_address_history"`, `null=True`, `blank=True` | Optional |
| `first_seen` | `DateTimeField(auto_now_add=True)` | -- | Automatically managed at creation |
| `last_seen` | `DateTimeField()` | -- | No `auto_now`, no `default` -- provided manually |

### 4.3 `natural_key_field_lookups`

```python
natural_key_field_lookups = ["device__name", "interface__name", "mac_address"]
```

### 4.4 Exact Meta class

```python
class Meta:
    verbose_name = "MAC Address History"
    verbose_name_plural = "MAC Address History"
    ordering = ["-last_seen"]
    constraints = [
        models.UniqueConstraint(
            fields=["device", "interface", "mac_address", "vlan"],
            name="nautobot_netdb_tracking_macaddresshistory_unique_mac_entry",
        ),
    ]
    indexes = [
        models.Index(fields=["mac_address", "last_seen"], name="idx_mac_lastseen"),
        models.Index(fields=["device", "last_seen"], name="idx_device_lastseen"),
        models.Index(fields=["interface", "last_seen"], name="idx_iface_lastseen"),
        models.Index(fields=["last_seen"], name="idx_mac_history_lastseen"),
        models.Index(fields=["first_seen"], name="idx_mac_history_firstseen"),
    ]
```

- `verbose_name_plural` identical to `verbose_name` (intentional)
- `UniqueConstraint` on 4 fields -- `vlan=NULL` treated as a distinct value by PostgreSQL
- Constraint name: `<app_label>_<model_lower>_<description>` (renamed in migration `0002`)
- 5 indexes total -- the index on `first_seen` added in migration `0003`

### 4.5 `__str__()`

```python
def __str__(self) -> str:
    vlan_str = f" (VLAN {self.vlan.vid})" if self.vlan else ""
    return f"{self.mac_address} on {self.device.name}:{self.interface.name}{vlan_str}"
```

### 4.6 Exact `clean()`

```python
def clean(self) -> None:
    super().clean()

    if self.mac_address:
        self.mac_address = normalize_mac_address(self.mac_address)

    if self.interface and self.device:
        if self.interface.device_id != self.device_id:
            raise ValidationError({"interface": "Interface must belong to the specified device"})

    if not self.last_seen:
        self.last_seen = timezone.now()
```

### 4.7 `update_or_create_entry()` -- CRITICAL NetDB Pattern

```python
@classmethod
def update_or_create_entry(
    cls,
    device: Device,
    interface: Interface,
    mac_address: str,
    vlan: VLAN | None = None,
) -> tuple["MACAddressHistory", bool]:
    normalized_mac = normalize_mac_address(mac_address)

    with transaction.atomic():
        existing = cls.objects.filter(
            device=device,
            interface=interface,
            mac_address=normalized_mac,
            vlan=vlan,
        ).first()

        if existing:
            existing.last_seen = timezone.now()
            existing.validated_save()
            return existing, False

        entry = cls(
            device=device,
            interface=interface,
            mac_address=normalized_mac,
            vlan=vlan,
            last_seen=timezone.now(),
        )
        entry.validated_save()
        return entry, True
```

---

## 5. Model: `ARPEntry`

### 5.1 Fields

| Field | Exact Django Type | Options | Notes |
| ----- | ----------------- | ------- | ----- |
| `device` | `ForeignKey(to=Device, ...)` | `on_delete=CASCADE`, `related_name="arp_entries"` | Required |
| `interface` | `ForeignKey(to=Interface, ...)` | `on_delete=SET_NULL`, `related_name="arp_entries"`, `null=True`, `blank=True` | Optional |
| `ip_address` | `GenericIPAddressField(protocol="both")` | -- | Accepts IPv4 and IPv6 |
| `ip_address_object` | `ForeignKey(to="ipam.IPAddress", ...)` | `on_delete=SET_NULL`, `related_name="arp_entries"`, `null=True`, `blank=True` | Auto-resolved to IPAM |
| `mac_address` | `CharField(max_length=17)` | -- | Format `XX:XX:XX:XX:XX:XX` |
| `first_seen` | `DateTimeField(auto_now_add=True)` | -- | Automatically managed |
| `last_seen` | `DateTimeField()` | -- | Provided manually |

### 5.2 Exact Meta class

```python
class Meta:
    verbose_name = "ARP Entry"
    verbose_name_plural = "ARP Entries"
    ordering = ["-last_seen"]
    constraints = [
        models.UniqueConstraint(
            fields=["device", "ip_address", "mac_address"],
            name="nautobot_netdb_tracking_arpentry_unique_arp_entry",
        ),
    ]
    indexes = [
        models.Index(fields=["ip_address", "last_seen"], name="idx_ip_lastseen"),
        models.Index(fields=["mac_address", "last_seen"], name="idx_arp_mac_lastseen"),
        models.Index(fields=["device", "last_seen"], name="idx_arp_device_lastseen"),
        models.Index(fields=["last_seen"], name="idx_arp_lastseen"),
        models.Index(fields=["first_seen"], name="idx_arp_firstseen"),
    ]
```

### 5.3 `__str__()`

```python
def __str__(self) -> str:
    return f"{self.ip_address} -> {self.mac_address} on {self.device.name}"
```

### 5.4 `resolve_ip_address_object()` (staticmethod)

```python
@staticmethod
def resolve_ip_address_object(ip_str: str) -> IPAddress | None:
    existing = IPAddress.objects.filter(host=ip_str).first()
    if existing:
        return existing

    prefix = Prefix.objects.net_contains(ip_str).order_by("-prefix_length").first()
    if not prefix:
        return None

    active_status = Status.objects.get_for_model(IPAddress).get(name="Active")
    new_ip = IPAddress(
        host=ip_str,
        mask_length=prefix.prefix_length,
        parent=prefix,
        status=active_status,
    )
    new_ip.validated_save()
    return new_ip
```

- Uses `host=ip_str` (Nautobot 3.x API, not `address=`)
- `parent=prefix` (Nautobot 3.x, not `namespace=`)

---

## 6. Model: `TopologyConnection`

### 6.1 Inner class `Protocol` (TextChoices)

```python
class Protocol(models.TextChoices):
    CDP = "CDP", "CDP"
    LLDP = "LLDP", "LLDP"
```

### 6.2 Fields

| Field | Exact Django Type | Options | Notes |
| ----- | ----------------- | ------- | ----- |
| `local_device` | `ForeignKey(to=Device, ...)` | `on_delete=CASCADE`, `related_name="topology_connections_local"` | Required |
| `local_interface` | `ForeignKey(to=Interface, ...)` | `on_delete=CASCADE`, `related_name="topology_connections_local"` | Required |
| `remote_device` | `ForeignKey(to=Device, ...)` | `on_delete=CASCADE`, `related_name="topology_connections_remote"` | Required |
| `remote_interface` | `ForeignKey(to=Interface, ...)` | `on_delete=CASCADE`, `related_name="topology_connections_remote"` | Required |
| `protocol` | `CharField(max_length=10, choices=Protocol.choices)` | -- | `"CDP"` or `"LLDP"` |
| `cable` | `ForeignKey(to=Cable, ...)` | `on_delete=SET_NULL`, `related_name="topology_connections"`, `null=True`, `blank=True` | Optional |
| `first_seen` | `DateTimeField(auto_now_add=True)` | -- | Automatically managed |
| `last_seen` | `DateTimeField()` | -- | Provided manually |

### 6.3 Exact Meta class

```python
class Meta:
    verbose_name = "Topology Connection"
    verbose_name_plural = "Topology Connections"
    ordering = ["-last_seen"]
    constraints = [
        models.UniqueConstraint(
            fields=["local_device", "local_interface", "remote_device", "remote_interface"],
            name="nautobot_netdb_tracking_topologyconnection_unique_topology_connection",
        ),
    ]
    indexes = [
        models.Index(fields=["local_device", "last_seen"], name="idx_topo_local_lastseen"),
        models.Index(fields=["remote_device", "last_seen"], name="idx_topo_remote_lastseen"),
        models.Index(fields=["protocol", "last_seen"], name="idx_topo_proto_lastseen"),
        models.Index(fields=["last_seen"], name="idx_topo_lastseen"),
        models.Index(fields=["first_seen"], name="idx_topo_firstseen"),
    ]
```

### 6.4 `__str__()`

```python
def __str__(self) -> str:
    return (
        f"{self.local_device.name}:{self.local_interface.name} <-> "
        f"{self.remote_device.name}:{self.remote_interface.name} ({self.protocol})"
    )
```

### 6.5 Exact `clean()`

```python
def clean(self) -> None:
    super().clean()

    if self.local_interface and self.local_device:
        if self.local_interface.device_id != self.local_device_id:
            raise ValidationError({"local_interface": "Local interface must belong to the local device"})

    if self.remote_interface and self.remote_device:
        if self.remote_interface.device_id != self.remote_device_id:
            raise ValidationError({"remote_interface": "Remote interface must belong to the remote device"})

    if self.local_device_id == self.remote_device_id and self.local_interface_id == self.remote_interface_id:
        raise ValidationError("Cannot create a connection from an interface to itself")

    if not self.last_seen:
        self.last_seen = timezone.now()
```

---

## 7. `first_seen` / `last_seen` Pattern

| Field | Django Configuration | Management |
| ----- | -------------------- | ---------- |
| `first_seen` | `DateTimeField(auto_now_add=True)` | Django fills it automatically, not editable |
| `last_seen` | `DateTimeField()` | No `auto_now`, no `default` -- managed manually |

### NetDB UPDATE vs INSERT Algorithm

```text
For each piece of data collected from a device:
  1. Normalize the key data (MAC, IP, etc.)
  2. Look for an existing record with the same business key combination
  3. If found -> UPDATE last_seen = now() (+ ancillary fields if changed)
  4. If not found -> INSERT new row (first_seen = auto, last_seen = now())

Result:
  - Stable data over 90 days -> 1 single record
    (first_seen = initial date, last_seen = date of last scan)
  - Data that changes -> new record with first_seen = date of the change
```

---

## 8. Critical Rules for Recreating a Similar Model

1. Always call `super().clean()` first in `clean()`
2. Always use `validated_save()` -- never direct `.save()`
3. Wrap DB operations in `transaction.atomic()`
4. Compare FKs by `_id` (e.g. `self.interface.device_id != self.device_id`) to avoid extra queries
5. `last_seen` without `auto_now` or `default` -> managed manually in `update_or_create_entry()`, initialized in `clean()` as fallback
6. `first_seen` with `auto_now_add=True` -> managed by Django, do not attempt to modify it
7. Explicit `related_name` on all FKs -- required when two FKs point to the same model
8. Constraint names: convention `<app_label>_<model_class_lower>_<description>` -- must be respected from the initial migration
9. `natural_key_field_lookups` required by Nautobot for natural imports/exports
10. `PrimaryModel` comes from `nautobot.apps.models` (not `nautobot.core.models`)
