# nautobot-route-tracking

A Nautobot 3.x plugin that collects and historizes routing table entries from network devices via NAPALM `get_route_to()`.

## Features

- **Historical tracking**: Maintains history of route entries with intelligent UPDATE vs INSERT logic (NetDB pattern)
- **ECMP support**: Each next-hop is stored as a separate `RouteEntry` row
- **Multi-vendor**: Cisco IOS/IOS-XE and Arista EOS via NAPALM
- **Parallel collection**: Nornir-based parallel job for large device fleets
- **Nautobot integration**: Native UI, REST API, Device tab, permissions

## Requirements

- Nautobot >= 3.0.6
- `nautobot-plugin-nornir`
- `nornir-napalm`

## Installation

```bash
pip install nautobot-route-tracking
```

Add to `nautobot_config.py`:

```python
PLUGINS = ["nautobot_route_tracking", "nautobot_plugin_nornir"]

PLUGINS_CONFIG = {
    "nautobot_route_tracking": {
        "retention_days": 90,
    },
    "nautobot_plugin_nornir": {
        "use_config_context": {"connection_options": True},
    },
}
```

Run migrations:

```bash
nautobot-server migrate
```

## Usage

Launch the **CollectRoutesJob** from Nautobot's Jobs UI (Route Tracking group). Target devices by role, location, tag, dynamic group, or individual device.

Launch **PurgeOldRoutesJob** to delete route entries older than the configured retention period.

## License

Apache 2.0
