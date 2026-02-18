# Installation Guide

This guide covers the installation of the **nautobot-route-tracking** plugin for Nautobot.

## Requirements

- Nautobot >= 3.0.6
- Python >= 3.10
- PostgreSQL 12 or later
- Redis (for Celery)
- `nautobot-plugin-nornir` >= 3.0.0
- `napalm` >= 5.0.0

## Installation

### From PyPI (recommended for production)

```bash
pip install nautobot-route-tracking
```

### From source

```bash
git clone https://github.com/tcheval/nautobot_route_tracking
cd nautobot_route_tracking
pip install -e .
```

## Configuration

### 1. Add to `nautobot_config.py`

Add both the route tracking plugin and its Nornir dependency to `PLUGINS`:

```python
PLUGINS = [
    "nautobot_plugin_nornir",
    "nautobot_route_tracking",
]
```

### 2. Configure plugin settings

Add plugin configuration to `PLUGINS_CONFIG`:

```python
PLUGINS_CONFIG = {
    "nautobot_plugin_nornir": {
        "use_config_context": {
            "connection_options": True,
        },
    },
    "nautobot_route_tracking": {
        # Retention period in days for route entries (default: 90)
        "route_retention_days": 90,

        # Number of Nornir parallel workers (default: 50)
        "nornir_workers": 50,

        # Timeout per device in seconds (default: 30)
        "device_timeout": 30,
    },
}
```

The `use_config_context.connection_options: True` setting allows Nornir jobs to read SSH port and connection options from each device's Config Context. This is required when devices use non-standard SSH ports (e.g., FakeNOS lab devices).

### 3. Run database migrations

```bash
nautobot-server migrate
```

### 4. Collect static files

```bash
nautobot-server collectstatic --no-input
```

### 5. Restart workers

After installing or upgrading the plugin, restart the Celery worker and scheduler so they load the new code:

```bash
# Docker Compose
docker restart nautobot-worker nautobot-scheduler

# systemd
sudo systemctl restart nautobot-worker nautobot-scheduler
```

## Nautobot data model prerequisites

The collection jobs require that devices in Nautobot are correctly configured before running. The following prerequisites must be met.

### Platform with `network_driver`

Every device targeted by the collection job must have a Platform assigned, and that Platform must have the `network_driver` field set. Without it, `nautobot-plugin-nornir` cannot build the Nornir inventory and will skip the device with error `E2004: Platform network_driver missing`.

Supported `network_driver` values:

| Vendor | `network_driver` | NAPALM `napalm_driver` |
| ------ | ---------------- | ---------------------- |
| Cisco IOS / IOS-XE | `cisco_ios` | `ios` |
| Cisco IOS-XR | `cisco_iosxr` | `iosxr` |
| Cisco NX-OS | `cisco_nxos` | `nxos_ssh` |
| Arista EOS | `arista_eos` | `eos` |
| Juniper JunOS | `juniper_junos` | `junos` |

**Note**: Palo Alto PAN-OS is not supported. The NAPALM PAN-OS driver raises `NotImplementedError` on `get_route_to()`. Devices with a PAN-OS platform are automatically skipped during collection.

### Platform with `napalm_driver`

The `napalm_driver` field on the Platform must also be set (e.g., `eos`, `ios`). The plugin uses this to configure the NAPALM connection inside Nornir after inventory initialization. Without it, NAPALM cannot open the device connection.

### SecretsGroup with SSH credentials

Every device must have a SecretsGroup assigned that provides:

- `username` secret (access type: `Generic`, secret role: `Username`)
- `password` secret (access type: `Generic`, secret role: `Password`)

The secrets can use any Nautobot-supported provider (`environment-variable`, `text-file`, HashiCorp Vault, etc.).

### SSH port (optional, for non-standard ports)

If a device uses a non-standard SSH port (e.g., a lab simulator), configure it via the device's **Config Context**:

```json
{
  "nautobot_plugin_nornir": {
    "connection_options": {
      "napalm": {
        "extras": {
          "optional_args": {
            "port": 6001
          }
        }
      },
      "netmiko": {
        "extras": {
          "port": 6001
        }
      }
    }
  }
}
```

This requires `use_config_context.connection_options: True` in `PLUGINS_CONFIG["nautobot_plugin_nornir"]` (already set in the configuration example above).

## Verify installation

Check that the plugin is correctly installed and loaded:

```bash
# Verify package installation
pip show nautobot-route-tracking

# Verify the model is accessible
docker exec nautobot nautobot-server nbshell --command \
  "from nautobot_route_tracking.models import RouteEntry; print(RouteEntry.objects.count())"
```

After restarting Nautobot, navigate to **Plugins > Route Tracking > Routes** in the UI to confirm the plugin is loaded.

## Docker Compose (AzQore stack)

For the AzQore development stack, the plugin is installed at image build time via the `Dockerfile`. After modifying the plugin source:

### Method 1: Rebuild image (persistent)

```bash
cd nautobot_route_tracking && git pull origin main && cd ..
docker compose build nautobot && docker compose up -d
docker exec nautobot nautobot-server migrate
docker exec nautobot nautobot-server collectstatic --no-input
```

### Method 2: Hot install (lost on next image recreate)

```bash
for c in nautobot nautobot-worker nautobot-scheduler; do
  docker exec $c rm -rf /tmp/nautobot_route_tracking
  docker cp ./nautobot_route_tracking $c:/tmp/nautobot_route_tracking
  docker exec $c pip install --force-reinstall --no-deps /tmp/nautobot_route_tracking
done
docker exec nautobot nautobot-server migrate
docker restart nautobot nautobot-worker nautobot-scheduler
```

Use `--force-reinstall --no-deps` to guarantee the new code is installed even if the package version number has not changed. Without these flags, `pip install --upgrade` is a no-op when the version is identical.

## Upgrading

```bash
pip install --upgrade nautobot-route-tracking
nautobot-server migrate
nautobot-server collectstatic --no-input
# Restart workers
docker restart nautobot-worker nautobot-scheduler
```

## Uninstalling

1. Remove `nautobot_route_tracking` from `PLUGINS` in `nautobot_config.py`
2. Remove its entry from `PLUGINS_CONFIG`
3. Restart Nautobot services
4. Optionally drop the plugin tables (the plugin migrations will not be reversed automatically):

```bash
pip uninstall nautobot-route-tracking
```

## Troubleshooting

### Plugin not appearing in the UI

Check that the package is installed in the same Python environment as Nautobot:

```bash
pip show nautobot-route-tracking
```

Check Nautobot logs for import errors:

```bash
docker compose logs nautobot | grep -i "route_tracking\|route-tracking"
```

### Migration errors

Ensure your database user has the necessary privileges:

```sql
GRANT ALL PRIVILEGES ON DATABASE nautobot TO nautobot;
```

Then re-run the migration:

```bash
nautobot-server migrate nautobot_route_tracking
```

### Collection jobs failing with "Platform network_driver missing"

The targeted device has no Platform assigned, or the Platform has an empty `network_driver` field. Set `network_driver` on the Platform in the Nautobot UI under **Devices > Platforms**.

### Collection jobs failing with authentication errors

1. Verify the device has a SecretsGroup assigned.
2. Verify the secrets resolve correctly: in the Nautobot shell, retrieve the secret value and confirm it matches the device credentials.
3. For cEOS lab devices, confirm the EOS configuration includes `management ssh` with `authentication mode password`. Without this, EOS only exposes `publickey` and `keyboard-interactive` methods, causing `BadAuthenticationType` with NAPALM.

### No routes collected despite successful job

1. Run the job with `commit=False` (dry-run) to see what would be collected without writing to the database.
2. Check the job logs for per-device warnings (e.g., empty `get_route_to()` result).
3. Confirm the device's routing table is populated: connect to the device directly and run the equivalent `show ip route` command.

## References

- [Nautobot App Development Guide](https://docs.nautobot.com/projects/core/en/stable/development/apps/)
- [nautobot-plugin-nornir documentation](https://docs.nautobot.com/projects/plugin-nornir/en/latest/)
- [NAPALM documentation](https://napalm.readthedocs.io/)
- [Nautobot Configuration Reference](https://docs.nautobot.com/projects/core/en/stable/user-guide/administration/configuration/)
