# NAPALM Research -- Network Route Collection

**Date**: 2026-02-18
**Sources**: napalm.readthedocs.io, github.com/napalm-automation/napalm, nornir_napalm docs

---

## 1. `get_route_to()` -- Complete API

### Exact Signature

```python
def get_route_to(
    self,
    destination: str = "",
    protocol: str = "",
    longer: bool = False,
) -> Dict[str, List[RouteDict]]:
```

**Parameters**:

- `destination`: CIDR prefix e.g. `"1.0.0.0/24"` -- empty string = all routes
- `protocol`: Protocol filter e.g. `"ospf"`, `"bgp"`, `"static"`, `"connected"` -- empty string = all
- `longer`: If `True`, also returns more specific sub-prefixes (support varies by driver)

### Exact Return Format

```python
{
    "1.0.0.0/24": [
        {
            "protocol": "BGP",
            "current_active": True,
            "last_active": True,
            "age": 105219,
            "next_hop": "172.17.17.17",
            "outgoing_interface": "GigabitEthernet0/1",
            "selected_next_hop": True,
            "preference": 20,
            "inactive_reason": "",
            "routing_table": "default",
            "protocol_attributes": {
                "local_as": 65001,
                "as_path": "2914 8403 54113",
                "communities": ["2914:1234", "2914:5678"],
                "preference2": -101,
                "remote_as": 2914,
                "local_preference": 100,
                "metric": 0,
                "metric2": 0,
            }
        }
    ]
}
```

Returns a **dict** of prefixes -> **list** of next-hops (ECMP possible). Each prefix can have multiple active or inactive next-hops.

---

## 2. All Route Dict Fields

| Field | Type | Description |
| ----- | ---- | ----------- |
| `protocol` | `str` | `"BGP"`, `"OSPF"`, `"STATIC"`, `"CONNECTED"`, `"ISIS"`, `"RIP"`, `"EIGRP"`, `"LOCAL"` |
| `current_active` | `bool` | Route currently installed in the FIB |
| `last_active` | `bool` | Was active at the last change |
| `age` | `int` | Age in seconds |
| `preference` | `int` | Administrative distance (AD: OSPF=110, BGP=20/200, STATIC=1, CONNECTED=0) |
| `next_hop` | `str` | Next-hop IP address (e.g. `"172.17.17.17"`) |
| `outgoing_interface` | `str` | Outgoing interface (e.g. `"GigabitEthernet0/1"`) |
| `selected_next_hop` | `bool` | Next-hop selected among multiple ECMP candidates |
| `inactive_reason` | `str` | Inactivity reason (empty string if active) |
| `routing_table` | `str` | VRF/table name (`"default"`, `"inet.0"` on JunOS, `"management"`, etc.) |
| `protocol_attributes` | `dict` | Protocol-specific attributes (see below) |

### `protocol_attributes` by Protocol

**BGP**:

```python
{
    "local_as": 65001,
    "remote_as": 2914,
    "as_path": "2914 8403 54113",
    "communities": ["2914:1234", "2914:5678"],
    "local_preference": 100,
    "preference2": -101,
    "metric": 0,
    "metric2": 0,
}
```

**OSPF**:

```python
{
    "metric": 110,
    "metric_type": "2",  # "1" or "2"
}
```

**STATIC / CONNECTED**:

```python
{}  # empty dict
```

---

## 3. Driver Support

| Driver | Platform | `get_route_to` | Notes |
| ------ | -------- | -------------- | ----- |
| `eos` | Arista EOS | **Yes** | Inconsistencies on CONNECTED (next_hop sometimes empty) |
| `ios` | Cisco IOS/IOS-XE | **Yes** | Well supported |
| `iosxr` | Cisco IOS-XR | **Yes** | Well supported |
| `junos` | Juniper JunOS | **Yes** | `routing_table="inet.0"` instead of `"default"` |
| `nxos` / `nxos_ssh` | Cisco NX-OS | **Yes** | Well supported |
| `panos` | Palo Alto PAN-OS | **No** | `NotImplementedError` -- community driver without implementation |
| `sros` | Nokia SR-OS | Partial | Limited support |

**For our lab**: `cisco_ios` -- supported, `arista_eos` -- supported, `panos` -- not supported (excluded from scope).

---

## 4. Return Examples by Driver

### Arista EOS -- OSPF route

```python
{
    "10.0.0.0/8": [
        {
            "protocol": "OSPF",
            "current_active": True,
            "last_active": True,
            "age": 3600,
            "next_hop": "192.168.1.1",
            "outgoing_interface": "Ethernet1",
            "selected_next_hop": True,
            "preference": 110,
            "inactive_reason": "",
            "routing_table": "default",
            "protocol_attributes": {"metric": 20, "metric_type": "2"},
        }
    ]
}
```

### Cisco IOS -- Static route

```python
{
    "0.0.0.0/0": [
        {
            "protocol": "STATIC",
            "current_active": True,
            "last_active": True,
            "age": 0,
            "next_hop": "10.0.0.1",
            "outgoing_interface": "GigabitEthernet0/1",
            "selected_next_hop": True,
            "preference": 1,
            "inactive_reason": "",
            "routing_table": "default",
            "protocol_attributes": {},
        }
    ]
}
```

### Cisco IOS -- ECMP BGP (2 next-hops)

```python
{
    "1.0.0.0/24": [
        {
            "protocol": "BGP",
            "current_active": True,
            "next_hop": "172.17.17.17",
            "outgoing_interface": "GigabitEthernet0/1",
            "preference": 20,
            "routing_table": "default",
            "protocol_attributes": {"remote_as": 65001, "as_path": "65001", ...},
        },
        {
            "protocol": "BGP",
            "current_active": True,
            "next_hop": "172.17.17.18",
            "outgoing_interface": "GigabitEthernet0/2",
            "preference": 20,
            "routing_table": "default",
            "protocol_attributes": {"remote_as": 65002, "as_path": "65002", ...},
        },
    ]
}
```

---

## 5. Critical Limitations

### BGP full table -- DANGER

- **Internet full table**: 900k+ routes in 2026 (IPv4 + IPv6)
- **NEVER** call `get_route_to(destination="", protocol="")` without a filter on a PE router
- `get_route_to(destination="", protocol="bgp")` returns millions of lines -> timeout + OOM
- Nautobot worker: memory limit 768 MiB -> OOM if BGP is unfiltered
- **Recommendation**: BGP excluded by default, with `BooleanVar(default=False)` and explicit warning

### PAN-OS -- Not Supported

```python
# napalm-panos community driver
def get_route_to(self, destination="", protocol="", longer=False):
    raise NotImplementedError("Feature not yet implemented.")
```

Exclude PAN-OS from the scope of `nautobot_route_tracking`.

### JunOS -- Different `routing_table`

- Returns `"inet.0"` instead of `"default"` -> store `routing_table` raw, do not transform
- `longer=True` may be silently ignored depending on the driver

### Arista EOS -- CONNECTED Routes

- `next_hop` sometimes empty string `""` for CONNECTED routes (directly connected interface)
- `outgoing_interface` contains the interface in this case
- Handle `next_hop = ""` or `next_hop = None` as valid values

---

## 6. `get_bgp_neighbors()` -- Alternative for BGP Peers

To collect BGP sessions without the prefixes (lower volume):

```python
{
    "global": {
        "router_id": "10.255.255.1",
        "peers": {
            "10.255.255.2": {
                "local_as": 65900,
                "remote_as": 65900,
                "is_up": True,
                "is_enabled": True,
                "uptime": 372,
                "address_family": {
                    "ipv4": {
                        "accepted_prefixes": 1500,
                        "received_prefixes": 1500,
                        "sent_prefixes": 100,
                    }
                },
            }
        },
    }
}
```

---

## 7. Recommendations for `nautobot_route_tracking`

### Collection Strategy

1. **Primary method**: `get_route_to()` via `nornir_napalm`
2. **Fallback**: Netmiko + TextFSM `show ip route` (same pattern as `collect_mac_arp.py`)
3. **BGP excluded by default** -- add `collect_bgp = BooleanVar(default=False)` with warning
4. **One call per enabled protocol** (OSPF, STATIC, CONNECTED separately) for granular control

### Recommended Job Variables

```python
collect_ospf = BooleanVar(default=True, description="Collect OSPF routes")
collect_static = BooleanVar(default=True, description="Collect static routes")
collect_connected = BooleanVar(default=True, description="Collect connected routes")
collect_bgp = BooleanVar(
    default=False,
    description="Collect BGP routes (WARNING: may be slow/OOM on PE routers with full table)"
)
```

### Prefixes to Exclude

```python
EXCLUDED_ROUTE_PREFIXES: tuple[str, ...] = (
    "224.0.0.0/4",     # IPv4 Multicast
    "239.0.0.0/8",     # IPv4 Multicast local
    "169.254.0.0/16",  # IPv4 Link-local
    "127.0.0.0/8",     # IPv4 Loopback
    "ff00::/8",        # IPv6 Multicast
    "fe80::/10",       # IPv6 Link-local
    "::1/128",         # IPv6 Loopback
)
```

### Normalized `protocol` Values

To avoid variations between drivers (EOS = `"OSPF"`, IOS = `"ospf"`, etc.), normalize to lowercase:

```python
PROTOCOL_CHOICES = [
    ("ospf", "OSPF"),
    ("bgp", "BGP"),
    ("static", "Static"),
    ("connected", "Connected"),
    ("isis", "IS-IS"),
    ("rip", "RIP"),
    ("eigrp", "EIGRP"),
    ("local", "Local"),
    ("unknown", "Unknown"),
]
```

Normalization: `entry["protocol"].lower()` before storage.

---

## 8. Nornir Integration -- Pattern to Use

```python
from nornir_napalm.plugins.tasks import napalm_get
from nornir.core.task import Result, Task

def collect_routes_task(task: Task, protocols: list[str]) -> Result:
    """Collect routing table entries via NAPALM get_route_to()."""
    host = task.host
    all_routes: dict[str, list] = {}

    for protocol in protocols:
        try:
            result = task.run(
                task=napalm_get,
                getters=["get_route_to"],
                getters_options={
                    "get_route_to": {
                        "destination": "",
                        "protocol": protocol,
                        "longer": False,
                    }
                },
                severity_level=20,  # INFO
            )
            protocol_routes = result.result.get("get_route_to", {})
            for prefix, nexthops in protocol_routes.items():
                all_routes.setdefault(prefix, []).extend(nexthops)

        except NornirSubTaskError as exc:
            root_cause = _extract_nornir_error(exc)
            # Fallback to Netmiko/TextFSM for this protocol
            ...

    return Result(host=host, result=all_routes)
```

---

## 9. Usage in `nautobot_netdb_tracking` -- NAPALM Getters Used

| Getter | File | Usage |
| ------ | ---- | ----- |
| `get_mac_address_table` | `collect_mac_arp.py` | MAC table collection |
| `get_arp_table` | `collect_mac_arp.py` | ARP table collection |
| `get_interfaces` | `collect_mac_arp.py` | Interface state sync |
| `get_vlans` | `collect_mac_arp.py` | VLAN/switchport sync |
| `get_lldp_neighbors_detail` | `collect_topology.py` | LLDP neighbor discovery |

**`get_route_to`** is not yet used -- this is the new getter to implement.

---

## 10. Proposed RouteEntry Data Model

Based on the fields from `get_route_to()`:

```python
class RouteEntry(PrimaryModel):
    device = models.ForeignKey("dcim.Device", on_delete=models.CASCADE)
    vrf = models.ForeignKey("ipam.VRF", on_delete=models.SET_NULL, null=True, blank=True)
    network = models.CharField(max_length=50)           # "10.0.0.0/8"
    prefix_length = models.PositiveSmallIntegerField()  # 8
    protocol = models.CharField(max_length=20, choices=PROTOCOL_CHOICES)  # "ospf"
    next_hop = models.CharField(max_length=50, blank=True)  # "192.168.1.1"
    outgoing_interface = models.ForeignKey("dcim.Interface", null=True, blank=True, on_delete=models.SET_NULL)
    metric = models.PositiveIntegerField(default=0)
    admin_distance = models.PositiveSmallIntegerField(default=0)  # preference
    is_active = models.BooleanField(default=True)       # current_active
    routing_table = models.CharField(max_length=100, default="default")  # VRF name raw
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField()
```

**UniqueConstraint**: `(device, vrf, network, next_hop, protocol)` -- ECMP = separate entries per next_hop.
