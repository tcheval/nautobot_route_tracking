# Usage Guide

This guide covers how to use the **nautobot-route-tracking** plugin to collect, consult, and manage IP routing table data from network devices.

## Overview

The Route Tracking plugin collects routing table entries from network devices using NAPALM `get_route_to()` and stores them in Nautobot with historical tracking. The core logic follows the NetDB pattern:

- **UPDATE `last_seen`**: If the exact same route entry (device + VRF + network + next_hop + protocol) is seen again, only the `last_seen` timestamp is updated. No duplicate record is created.
- **INSERT new record**: If any part of the combination changes (new next-hop, new protocol, route removed then re-added), a new record is created with `first_seen = last_seen = now`.

This gives you a compact history of actual routing changes rather than redundant snapshots.

## Key concept: UPDATE vs INSERT logic

```
Device A collected at T1:
  RouteEntry(device=A, network=10.0.0.0/8, next_hop=192.168.1.1, protocol=ospf)
    → first_seen=T1, last_seen=T1

Device A collected at T2 (same route still present):
  → first_seen=T1, last_seen=T2   (UPDATE only)

Device A collected at T3 (next-hop changed to 192.168.1.2):
  → New record: first_seen=T3, last_seen=T3  (INSERT)
  → Old record last_seen stays at T2
```

A route that disappears from the device stops getting `last_seen` updates. After `route_retention_days` days without update, it becomes a candidate for purge.

---

## Running the collection job

### From the UI

1. Navigate to **Extras > Jobs** in Nautobot.
2. Find the job **Collect Routing Tables** under the **Route Tracking** group.
3. Click **Run**.

#### Available filters (scope)

The job collects routes from all devices by default. Use these optional filters to narrow the scope:

| Parameter | Type | Description |
| --------- | ---- | ----------- |
| Device | ObjectVar | Collect only from a specific device |
| Location | ObjectVar | Collect from all devices in a location |
| Role | ObjectVar | Collect from all devices with a given role |
| DynamicGroup | ObjectVar | Collect from all devices in a dynamic group |
| Tag | MultiObjectVar | Collect from devices having all specified tags |

Leave all filter fields empty to collect from all devices that have a compatible Platform (with `network_driver` and `napalm_driver` set).

#### Protocol selection

| Parameter | Default | Description |
| --------- | ------- | ----------- |
| Collect OSPF | True | Collect OSPF routes |
| Collect Static | True | Collect static routes |
| Collect Connected | True | Collect directly connected routes |
| Collect BGP | **False** | Collect BGP routes — **WARNING: may cause timeout or OOM on PE routers with a full BGP table (900k+ routes)** |
| VRF name | (empty) | If set, collect only from this VRF/routing table. Leave empty for the default VRF. |

#### Execution options

| Parameter | Default | Range | Description |
| --------- | ------- | ----- | ----------- |
| workers | 50 | 1–100 | Number of parallel Nornir workers |
| timeout | 30 | 10–300 | Per-device connection timeout in seconds |
| commit | True | — | If False, runs in dry-run mode: collects data and logs what would be written, but makes no database changes |

**Best practice**: always run with `commit=False` first when targeting new devices or after a plugin upgrade, to verify collection works as expected before writing to the database.

### From the REST API

```bash
# List all jobs to find the job UUID
curl -s -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  "http://localhost:8080/api/extras/jobs/?name=Collect+Routing+Tables" | python3 -m json.tool

# Run the job (replace <job-id> with the UUID from above)
curl -X POST \
  -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  -H "Content-Type: application/json" \
  "http://localhost:8080/api/extras/jobs/<job-id>/run/" \
  -d '{
    "data": {
      "workers": 50,
      "timeout": 30,
      "collect_ospf": true,
      "collect_static": true,
      "collect_connected": true,
      "collect_bgp": false,
      "commit": true
    },
    "commit": true
  }'
```

**Important**: both `"commit": true` inside `data` and `"commit": true` at the top level are required. The top-level `commit` is the Nautobot job execution flag; `data.commit` is the plugin-level dry-run toggle that controls whether route entries are actually written to the database.

### Monitor job execution

Navigate to **Extras > Job Results** in the UI. Each device's collection result is logged with the device name as the grouping. A failed device does not abort the job — the job only marks itself as FAILURE if zero devices succeeded (which would indicate a global infrastructure problem).

---

## Consulting collected routes

### From the UI

Navigate to **Plugins > Route Tracking > Routes**.

The list view shows all collected route entries with the following columns:

| Column | Description |
| ------ | ----------- |
| Device | Device where this route was seen |
| VRF | VRF/routing table name (empty = default VRF) |
| Network | Destination prefix (e.g., `10.0.0.0/8`) |
| Next Hop | IP address of the next hop |
| Protocol | Routing protocol (ospf, bgp, static, connected, …) |
| Metric | Route metric |
| Admin Distance | Administrative distance (preference) |
| Active | Whether the route is installed in the FIB |
| First Seen | When this route entry was first observed |
| Last Seen | When this route entry was last observed |

#### UI filters

Use the filter sidebar (click the **Filters** button) to narrow results:

| Filter | Description |
| ------ | ----------- |
| Device | Filter by device name or UUID |
| VRF | Filter by VRF name or UUID |
| Protocol | Filter by protocol (ospf, bgp, static, connected, …) |
| Network | Partial match on the network prefix (e.g., `10.0` matches `10.0.0.0/8` and `10.0.1.0/24`) |
| Next Hop | Filter by next-hop IP address |
| Is Active | Filter active (FIB) or inactive (RIB-only) routes |
| q | Global text search across device name, network, and next-hop fields |

### Device tab "Routes"

On the detail page of any device, a **Routes** tab is added by the plugin. It shows all route entries currently tracked for that device, with the same filters as the main list view but pre-filtered to the device.

### From the REST API

#### List routes

```bash
curl -s -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  "http://localhost:8080/api/plugins/route-tracking/routes/" | python3 -m json.tool
```

#### Filter routes

```bash
# Routes for a specific device
curl -s -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  "http://localhost:8080/api/plugins/route-tracking/routes/?device=paris-rtr-01"

# OSPF routes
curl -s -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  "http://localhost:8080/api/plugins/route-tracking/routes/?protocol=ospf"

# Routes matching a prefix (partial match)
curl -s -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  "http://localhost:8080/api/plugins/route-tracking/routes/?network=10.0"
```

#### Route entry JSON format

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "url": "http://localhost:8080/api/plugins/route-tracking/routes/3fa85f64-5717-4562-b3fc-2c963f66afa6/",
  "display": "paris-rtr-01 | 10.0.0.0/8 via 192.168.1.1 (ospf)",
  "device": {
    "id": "...",
    "name": "paris-rtr-01",
    "url": "http://localhost:8080/api/dcim/devices/.../"
  },
  "vrf": null,
  "network": "10.0.0.0/8",
  "prefix_length": 8,
  "next_hop": "192.168.1.1",
  "outgoing_interface": {
    "id": "...",
    "name": "Ethernet1",
    "url": "http://localhost:8080/api/dcim/interfaces/.../"
  },
  "protocol": "ospf",
  "metric": 20,
  "admin_distance": 110,
  "is_active": true,
  "routing_table": "default",
  "first_seen": "2026-02-18T08:00:00.000000Z",
  "last_seen": "2026-02-18T14:30:00.000000Z",
  "created": "2026-02-18T08:00:00.000000Z",
  "last_updated": "2026-02-18T14:30:00.000000Z"
}
```

#### Get a specific route entry

```bash
curl -s -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  "http://localhost:8080/api/plugins/route-tracking/routes/<uuid>/"
```

---

## Purging old route entries

### From the UI

Navigate to **Extras > Jobs > Purge Old Routes** and run the job.

| Parameter | Default | Description |
| --------- | ------- | ----------- |
| retention_days | 90 | Delete route entries not seen for more than this many days |
| commit | False | If False, dry-run: counts what would be deleted without deleting |

**Always run with `commit=False` first** to verify the purge scope before committing. The dry-run output shows how many entries would be deleted per device.

### From the REST API

```bash
# Find the Purge Old Routes job UUID
curl -s -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  "http://localhost:8080/api/extras/jobs/?name=Purge+Old+Routes" | python3 -m json.tool

# Dry-run (commit=false in data)
curl -X POST \
  -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  -H "Content-Type: application/json" \
  "http://localhost:8080/api/extras/jobs/<job-id>/run/" \
  -d '{"data": {"retention_days": 90, "commit": false}, "commit": true}'

# Actual purge
curl -X POST \
  -H "Authorization: Token c930c96c0ae586cfbd451cc2fc843198dfc411f6" \
  -H "Content-Type: application/json" \
  "http://localhost:8080/api/extras/jobs/<job-id>/run/" \
  -d '{"data": {"retention_days": 90, "commit": true}, "commit": true}'
```

---

## Interpreting the data

### `first_seen` and `last_seen`

- `first_seen`: the timestamp when this exact route (device + VRF + network + next_hop + protocol) was first recorded in Nautobot. This is set once and never updated.
- `last_seen`: the timestamp of the most recent collection job run in which this route was present on the device. Updated on every successful collection where the route is still present.

A route entry where `last_seen` is several days old indicates the route was no longer present on the device at the time of the last collection. It may have been withdrawn, the device may have changed its routing policy, or the collection job may have failed for that device.

### `is_active`

Corresponds to the NAPALM `current_active` field:

- `True`: the route is installed in the FIB (Forwarding Information Base). It is actively used for packet forwarding.
- `False`: the route is present in the RIB (Routing Information Base) but not selected for forwarding — for example, a backup BGP path with a worse local preference, or a floating static route with a higher admin distance.

### ECMP routes

When multiple next-hops exist for the same prefix (Equal-Cost Multi-Path), each next-hop is stored as a separate `RouteEntry` record with the same `network` and `protocol` but a different `next_hop`. The UniqueConstraint is on `(device, vrf, network, next_hop, protocol)`, so ECMP is fully supported.

Example (BGP ECMP via two peers):

```
network: 1.0.0.0/24 | next_hop: 172.17.17.17 | protocol: bgp | is_active: True
network: 1.0.0.0/24 | next_hop: 172.17.17.18 | protocol: bgp | is_active: True
```

### Protocol values

Protocols are stored normalized to lowercase regardless of what the device returns:

| Stored value | Description |
| ------------ | ----------- |
| `ospf` | OSPF (Open Shortest Path First) |
| `bgp` | BGP (Border Gateway Protocol) |
| `static` | Statically configured route |
| `connected` | Directly connected network |
| `isis` | IS-IS |
| `rip` | RIP |
| `eigrp` | EIGRP (Cisco proprietary) |
| `local` | Local route (router's own interface address) |
| `unknown` | Protocol not recognized by the driver |

### Excluded prefixes

The following prefixes are always excluded from collection and storage to avoid noise:

- `224.0.0.0/4` — IPv4 multicast
- `239.0.0.0/8` — IPv4 local multicast
- `169.254.0.0/16` — IPv4 link-local
- `127.0.0.0/8` — IPv4 loopback
- `ff00::/8` — IPv6 multicast
- `fe80::/10` — IPv6 link-local
- `::1/128` — IPv6 loopback

---

## Best practices

### Start with dry-run

Always run **Collect Routing Tables** with `commit=False` first, especially when:

- Running against a new set of devices for the first time
- After upgrading the plugin
- When troubleshooting unexpected results

The dry-run logs what would be collected per device without writing to the database.

### Avoid BGP on PE routers

Do not enable **Collect BGP** on Internet-facing PE routers with a full BGP table (900k+ IPv4 + IPv6 prefixes in 2026). This causes:

- Extremely long collection time (minutes per device)
- Risk of OOM in the Nautobot worker container (limited to 768 MiB by default)
- Potential timeout for other jobs sharing the Celery worker

If BGP tracking is required, limit the scope to specific devices (internal RR, edge routers with only customer routes) and increase `device_timeout` accordingly.

### Use appropriate worker counts

For large environments:

- Start with 50 workers (the default)
- Monitor Nautobot worker memory usage (`docker stats nautobot-worker`)
- Reduce if memory usage exceeds 600 MiB (worker limit is 768 MiB in the AzQore stack)
- Reduce if device connections are throttled (e.g., network ACLs limiting concurrent SSH)

### Schedule regular collection

The collection job is designed for manual or scheduled execution. Typical intervals:

- Routing table collection: every 4–6 hours
- Purge old data: once per day (scheduled at off-peak hours)

### Monitor job results

After each collection run, check **Extras > Job Results** for:

- Devices that failed (connection error, auth failure, unsupported platform)
- Devices that returned an empty routing table (may indicate a driver issue)
- Collection time — if it consistently exceeds 5 minutes, consider reducing the device scope per job run or increasing parallelism

---

## Troubleshooting

### No data collected

1. Verify devices have a Platform with both `network_driver` and `napalm_driver` configured.
2. Check that devices have a SecretsGroup with valid SSH credentials.
3. Run the job in dry-run mode and review per-device log messages in the Job Result detail view.
4. Test connectivity manually from the Nautobot container: `docker exec nautobot nc -zv <device-ip> 22`.

### Stale data (routes not updating)

1. Check if the collection job is running successfully (Extras > Job Results).
2. Verify the device is reachable: connection errors silently skip a device without failing the entire job.
3. Check if `last_seen` is being updated for any routes on that device — if not, the device is being skipped.

### Performance issues

1. Reduce `workers` (fewer parallel SSH connections consume less memory).
2. Increase `timeout` if devices are slow to respond to `get_route_to()`.
3. Disable `collect_bgp` if enabled — BGP is the dominant source of slowness.
4. Scope the job to specific locations or roles instead of running against all devices.

## References

- [Nautobot Jobs Documentation](https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/jobs/)
- [Nautobot REST API](https://docs.nautobot.com/projects/core/en/stable/user-guide/platform-functionality/rest-api/)
- [NAPALM `get_route_to()` documentation](https://napalm.readthedocs.io/en/latest/base.html#napalm.base.base.NetworkDriver.get_route_to)
- [nautobot-plugin-nornir documentation](https://docs.nautobot.com/projects/plugin-nornir/en/latest/)
