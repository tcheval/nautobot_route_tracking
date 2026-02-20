## Essential Reading

**Before writing any code**, read **[docs/nautobot_plugin_dev_lessons.md](docs/nautobot_plugin_dev_lessons.md)** — a guide of hard-won lessons covering Nornir parallelism, NautobotORMInventory quirks, Nautobot 3.x pitfalls, and testing patterns.

For specifications, see **[docs/SPECIFICATIONS.md](docs/SPECIFICATIONS.md)** — the authoritative data model, collection strategy, and feature scope.

## Project Overview

**nautobot-route-tracking** is a Nautobot plugin that collects and historizes routing table entries from network devices via NAPALM CLI commands (`napalm_cli`). It follows the same UPDATE/INSERT logic as [nautobot-netdb-tracking](https://github.com/tcheval/nautobot-netdb-tracking), tracking route changes over time with full history.

### Key Objectives

1. **Historical Tracking**: Maintain 90-day history of route entries with intelligent UPDATE vs INSERT logic
2. **Enterprise Scale**: Handle large device fleets with parallel collection (Nornir)
3. **Multi-vendor Support**: Cisco IOS/IOS-XE, Arista EOS (NAPALM drivers)
4. **ECMP Support**: Each next-hop is a separate `RouteEntry` row (UniqueConstraint includes `next_hop`)
5. **Nautobot Integration**: Native UI, API, permissions, Device tab, and data models

## Architecture Principles

### Network-to-Code Standards

This project **strictly follows** [Network-to-Code best practices](https://github.com/nautobot/cookiecutter-nautobot-app):

1. **`validated_save()` ALWAYS**: Never use `.save()` directly
2. **Structured Logging**: Use `self.logger.info(..., extra={"grouping": device.name})`
3. **Error Handling**: Graceful degradation — one device failure shouldn't crash the entire job
4. **Transactions**: Use `transaction.atomic()` for database operations
5. **Type Hints**: Python 3.10+ type hints throughout

### NEVER Degrade Production Code for Test Infrastructure (CRITICAL)

**Production code follows industry standards. Period.** If a test tool (FakeNOS, mock, simulator) doesn't behave correctly, the problem is the test tool — not the production code.

Never:
- Add `if fakenos:` branches in job code
- Skip NAPALM because a simulator returns bad data
- Loosen validation or error handling to tolerate bad test data

The correct approach is **always** to fix the test infrastructure.

### NetDB Logic (CRITICAL)

The core differentiator from simple polling is the **UPDATE vs INSERT** logic:

```python
@classmethod
def update_or_create_entry(cls, device, network, protocol, vrf=None, next_hop="", **kwargs):
    with transaction.atomic():
        existing = cls.objects.filter(
            device=device, vrf=vrf, network=network,
            next_hop=next_hop, protocol=protocol,
        ).first()
        if existing:
            # Route unchanged — just update last_seen
            existing.last_seen = timezone.now()
            for field, value in kwargs.items():
                setattr(existing, field, value)
            existing.validated_save()
            return existing, False
        # New route or changed attributes — insert new record
        entry = cls(
            device=device, vrf=vrf, network=network,
            next_hop=next_hop, protocol=protocol,
            last_seen=timezone.now(), **kwargs
        )
        entry.validated_save()
        return entry, True
```

**Result**: History only contains actual changes, not redundant snapshots. ECMP routes (same prefix, different next-hops) are separate rows.

## Data Model

### RouteEntry (single model)

```python
class RouteEntry(PrimaryModel):
    class Protocol(models.TextChoices):
        OSPF      = "ospf",      "OSPF"
        BGP       = "bgp",       "BGP"
        STATIC    = "static",    "Static"
        CONNECTED = "connected", "Connected"
        ISIS      = "isis",      "IS-IS"
        RIP       = "rip",       "RIP"
        EIGRP     = "eigrp",     "EIGRP"
        LOCAL     = "local",     "Local"
        UNKNOWN   = "unknown",   "Unknown"

    device            = ForeignKey("dcim.Device", CASCADE, related_name="route_entries")
    vrf               = ForeignKey("ipam.VRF", SET_NULL, null=True, blank=True)
    network           = CharField(max_length=50)             # "10.0.0.0/8"
    prefix_length     = PositiveSmallIntegerField()          # 8
    protocol          = CharField(max_length=20, choices=Protocol.choices)
    next_hop          = CharField(max_length=50, blank=True, default="")
    outgoing_interface = ForeignKey("dcim.Interface", SET_NULL, null=True, blank=True)
    metric            = PositiveIntegerField(default=0)
    admin_distance    = PositiveSmallIntegerField(default=0) # "preference" in NAPALM
    is_active         = BooleanField(default=True)           # "current_active" in NAPALM
    routing_table     = CharField(max_length=100, default="default")  # raw VRF name
    first_seen        = DateTimeField(auto_now_add=True)
    last_seen         = DateTimeField()

    class Meta:
        ordering = ["-last_seen"]
        constraints = [UniqueConstraint(
            fields=["device", "vrf", "network", "next_hop", "protocol"],
            name="nautobot_route_tracking_routeentry_unique_route",
        )]
```

### UniqueConstraint key points

- `vrf=NULL` means global routing table (no VRF)
- ECMP = two rows with same `(device, vrf, network, protocol)` but different `next_hop`
- Protocol normalized to **lowercase** before storage (EOS returns `"OSPF"`, IOS returns `"ospf"`)

## NAPALM CLI Collection (platform-specific, no fallback)

Collection uses `napalm_cli` with platform-specific commands (not `napalm_get`/`get_route_to()`):

- **Arista EOS**: `show ip route | json` → structured JSON, parsed directly by `_parse_eos_routes()`
- **Cisco IOS**: `show ip route` → text output, parsed via TextFSM (`ntc-templates`)

```python
# EOS example
sub_result = task.run(task=napalm_cli, commands=["show ip route | json"], severity_level=logging.DEBUG)
routes = _parse_eos_routes(sub_result[0].result["show ip route | json"])

# IOS example
sub_result = task.run(task=napalm_cli, commands=["show ip route"], severity_level=logging.DEBUG)
routes = _parse_ios_routes(sub_result[0].result["show ip route"])
# routes: dict[prefix_str, list[nexthop_dict]]
```

**Key facts**:
- Each prefix maps to a **list** of next-hop dicts (ECMP = multiple entries in the list)
- EOS `routeType` values (e.g. `"eBGP"`, `"ospfExt1"`) are normalized via `_EOS_PROTOCOL_MAP`
- IOS protocol codes (e.g. `"O"`, `"B"`, `"S"`) are normalized via `_IOS_PROTOCOL_MAP`
- Arista EOS CONNECTED routes: `next_hop` can be empty string `""` → `outgoing_interface` carries the interface
- VRF routing tables: EOS returns VRF names from `show ip route vrf all`, IOS TextFSM extracts VRF field

**Excluded prefixes** (defined in `models.py`):

```python
EXCLUDED_ROUTE_NETWORKS: tuple[str, ...] = (
    "224.0.0.0/4",    # IPv4 Multicast (includes 239.0.0.0/8)
    "169.254.0.0/16", # IPv4 Link-local
    "127.0.0.0/8",    # IPv4 Loopback
    "ff00::/8",       # IPv6 Multicast
    "fe80::/10",      # IPv6 Link-local
    "::1/128",        # IPv6 Loopback
)
```

## Job Variables

### CollectRoutesJob

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `device` | `ObjectVar` | None | Single device target |
| `dynamic_group` | `ObjectVar` | None | Dynamic group target |
| `device_role` | `MultiObjectVar` | None | Role filter |
| `location` | `MultiObjectVar` | None | Location filter (includes descendants) |
| `tag` | `MultiObjectVar` | None | Tag filter |
| `workers` | `IntegerVar` | 50 | Nornir parallel workers |
| `timeout` | `IntegerVar` | 30 | Per-device timeout (seconds) |
| `commit` | `BooleanVar` | True | Write to DB (False = dry-run) |
| `debug_mode` | `BooleanVar` | False | Verbose logging |

**Device selection priority**: `device` > `dynamic_group` > `role`/`location`/`tag`

**Supported platforms**: Cisco IOS (`cisco_ios`) and Arista EOS (`arista_eos`) only. PAN-OS excluded (`get_route_to` raises `NotImplementedError` in the community driver).

### PurgeOldRoutesJob

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `retention_days` | `IntegerVar` | 90 | Delete entries older than N days |
| `commit` | `BooleanVar` | True | Write to DB (False = dry-run) |

## Code Structure

```
nautobot_route_tracking/
├── __init__.py                 # NautobotAppConfig
├── models.py                   # RouteEntry + EXCLUDED_ROUTE_NETWORKS + normalize helpers
├── views.py                    # NautobotUIViewSet + DeviceRouteTabView
├── filters.py                  # RouteEntryFilterSet
├── tables.py                   # RouteEntryTable, RouteEntryDeviceTable
├── forms.py                    # RouteEntryFilterForm
├── urls.py                     # NautobotUIViewSetRouter + device tab URL
├── navigation.py               # NavMenuTab "Route Tracking"
├── template_content.py         # DeviceRouteTab (TemplateExtension)
├── signals.py                  # post_migrate: enable jobs
├── admin.py                    # Django admin registration
├── api/
│   ├── __init__.py
│   ├── serializers.py          # RouteEntrySerializer
│   ├── views.py                # RouteEntryViewSet
│   └── urls.py                 # OrderedDefaultRouter
├── jobs/
│   ├── __init__.py             # register_jobs(CollectRoutesJob, PurgeOldRoutesJob)
│   ├── _base.py                # BaseCollectionJob + utilities
│   └── collect_routes.py       # CollectRoutesJob
│   └── purge_old_routes.py     # PurgeOldRoutesJob
└── templates/nautobot_route_tracking/
    ├── device_route_tab.html
    └── inc/
        └── device_route_panel.html
```

## Critical Pitfalls

### `register_jobs` — OBLIGATOIRE dans `jobs/__init__.py`

```python
# jobs/__init__.py
from nautobot.core.celery import register_jobs
from .collect_routes import CollectRoutesJob
from .purge_old_routes import PurgeOldRoutesJob

jobs = [CollectRoutesJob, PurgeOldRoutesJob]
register_jobs(*jobs)
```

Sans `register_jobs()` au niveau module, les jobs n'apparaissent pas dans l'UI Nautobot.

### NornirSubTaskError — `result` est un `MultiResult` (liste)

```python
# MAUVAIS — exc.result.exception n'existe pas (c'est une liste)
except NornirSubTaskError as exc:
    error = exc.result.exception  # AttributeError!

# BON — itérer le MultiResult
def _extract_nornir_error(exc: NornirSubTaskError) -> str:
    if hasattr(exc, "result"):
        for r in exc.result:
            if r.failed:
                if r.exception:
                    return str(r.exception)
                if r.result:
                    return str(r.result)
    return str(exc)
```

### NaturalKeyOrPKMultipleChoiceFilter — input LIST obligatoire

```python
# MAUVAIS — bare string
filterset = RouteEntryFilterSet({"device": str(device.pk)})

# BON — liste de strings
filterset = RouteEntryFilterSet({"device": [str(device.pk)]})
filterset = RouteEntryFilterSet({"vrf": [str(vrf.pk)]})
```

### Templates — toujours `inc/table.html`

```django
{% render_table table "inc/table.html" %}              {# CORRECT #}
{% render_table table "django_tables2/bootstrap5.html" %}  {# WRONG #}
```

### Paginator — `EnhancedPaginator` obligatoire

```python
from nautobot.core.views.paginator import EnhancedPaginator, get_paginate_count
per_page = get_paginate_count(request)
RequestConfig(request, paginate={"per_page": per_page, "paginator_class": EnhancedPaginator}).configure(table)
```

### Tab templates — étendre `generic/object_detail.html`

```django
{% extends "generic/object_detail.html" %}  {# CORRECT pour les tabs #}
{% extends "base.html" %}                   {# WRONG pour les tabs #}
```

### `{% load %}` sur lignes séparées

```django
{% load helpers humanize %}
{% load render_table from django_tables2 %}
```

Jamais sur la même ligne avec `from` — Django misparse.

### RuntimeError — uniquement si zéro succès

```python
# MAUVAIS — 3 devices down sur 100 = job FAILURE
if self.stats["devices_failed"] > 0:
    raise RuntimeError(msg)

# BON — FAILURE uniquement si aucun device n'a réussi
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(msg)
```

### `validated_save()` — JAMAIS `.save()`

```python
entry.validated_save()   # CORRECT
entry.save()             # INTERDIT
```

## Testing Standards

### Factory Boy

```python
import factory
from nautobot.dcim.models import Device
from nautobot_route_tracking.models import RouteEntry

class RouteEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RouteEntry

    device = factory.SubFactory(DeviceFactory)
    vrf = None
    network = factory.Sequence(lambda n: f"10.{n}.0.0/24")
    prefix_length = 24
    protocol = RouteEntry.Protocol.OSPF
    next_hop = factory.Sequence(lambda n: f"192.168.0.{n}")
    outgoing_interface = None
    metric = 10
    admin_distance = 110
    is_active = True
    routing_table = "default"
    last_seen = factory.LazyFunction(timezone.now)
```

**Note** : toujours `validated_save()` dans les fixtures — jamais `.create()` ou `.save()`.

### Filter tests — format LIST

```python
filterset = RouteEntryFilterSet({"device": [str(device.pk)]})
assert filterset.is_valid(), filterset.errors
filterset = RouteEntryFilterSet({"network": "10.0.0"})  # CharFilter = bare string
```

### Tests jobs — mocker les appels réseau

```python
@patch("nautobot_route_tracking.jobs.collect_routes.napalm_get")
def test_collect_routes_job(mock_napalm_get, ...):
    mock_napalm_get.return_value = {"get_route_to": {"10.0.0.0/24": [...]}}
    ...
```

## Development Workflow

### Lint et formatage

```bash
ruff check nautobot_route_tracking/
ruff format --check nautobot_route_tracking/
```

### Tests

```bash
pytest tests/ -v
```

### Déploiement à chaud (développement)

```bash
for c in nautobot nautobot-worker nautobot-scheduler; do
  docker exec $c rm -rf /tmp/nautobot_route_tracking
  docker cp ./nautobot_route_tracking $c:/tmp/nautobot_route_tracking
  docker exec $c pip install --force-reinstall --no-deps /tmp/nautobot_route_tracking
done
docker exec nautobot nautobot-server makemigrations nautobot_route_tracking
docker exec nautobot nautobot-server migrate
docker restart nautobot nautobot-worker nautobot-scheduler
```

### Migrations

```bash
docker exec nautobot nautobot-server makemigrations nautobot_route_tracking
docker exec nautobot nautobot-server migrate
```

## Swarm Mode (Multi-Agent Parallel Execution)

Pour les tâches complexes touchant plusieurs fichiers ou domaines indépendants, utiliser le **mode swarm** : lancer plusieurs agents Claude en parallèle via l'outil `Task`.

### Quand utiliser le swarm

- Refactoring multi-fichiers (models + views + tables + filters + templates)
- Ajout de tests pour plusieurs modules indépendants
- Implémentation de features indépendantes en parallèle
- Audit/review de différentes parties du codebase

### Règles critiques

- **Lire avant d'écrire** : chaque agent DOIT lire les fichiers existants avant modification
- **Pas de conflits** : deux agents ne doivent JAMAIS modifier le même fichier
- **Conventions** : chaque agent respecte les standards du CLAUDE.md (`validated_save`, type hints, etc.)
- **Rapport** : chaque agent retourne un résumé clair de ce qu'il a fait/trouvé

---

**Last Updated**: 2026-02-18

**For AI Assistants**: This document provides the essential context for the `nautobot_route_tracking` plugin. Always prioritize Network-to-Code standards, the NetDB UPDATE/INSERT logic, and NAPALM-only collection via `get_route_to()`. For complex tasks, use swarm mode to parallelize independent work.
