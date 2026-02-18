# Specifications techniques — nautobot_route_tracking

**Version** : 0.1.0
**Date** : 2026-02-18
**Statut** : Approuvé

---

## 1. Data Model — `RouteEntry`

### Héritage

```python
from nautobot.apps.models import PrimaryModel

class RouteEntry(PrimaryModel):
```

`PrimaryModel` fournit : `id` (UUID PK), `created`, `last_updated`, `_custom_field_data`, `tags`, mixins Nautobot.

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

Valeurs stockées en DB en **lowercase** (normalisation depuis NAPALM qui retourne uppercase).

### Champs

| Champ | Type Django exact | Options | Notes |
| ----- | ----------------- | ------- | ----- |
| `device` | `ForeignKey("dcim.Device")` | `on_delete=CASCADE`, `related_name="route_entries"` | Obligatoire |
| `vrf` | `ForeignKey("ipam.VRF")` | `on_delete=SET_NULL`, `null=True`, `blank=True`, `related_name="route_entries"` | `NULL` = table globale |
| `network` | `CharField(max_length=50)` | — | Ex. `"10.0.0.0/8"` |
| `prefix_length` | `PositiveSmallIntegerField()` | — | Extrait de `network` dans `clean()` |
| `protocol` | `CharField(max_length=20, choices=Protocol.choices)` | — | Stocké lowercase |
| `next_hop` | `CharField(max_length=50, blank=True)` | `default=""` | Vide pour routes CONNECTED |
| `outgoing_interface` | `ForeignKey("dcim.Interface")` | `on_delete=SET_NULL`, `null=True`, `blank=True`, `related_name="route_entries"` | Optionnel |
| `metric` | `PositiveIntegerField(default=0)` | — | Coût de la route |
| `admin_distance` | `PositiveSmallIntegerField(default=0)` | — | Champ `preference` NAPALM |
| `is_active` | `BooleanField(default=True)` | — | Champ `current_active` NAPALM |
| `routing_table` | `CharField(max_length=100, default="default")` | — | Nom VRF brut depuis NAPALM (ex. `"inet.0"` sur JunOS) |
| `first_seen` | `DateTimeField(auto_now_add=True)` | — | Géré automatiquement |
| `last_seen` | `DateTimeField()` | — | Géré manuellement dans `update_or_create_entry()` |

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
    ]
    indexes = [
        models.Index(fields=["device", "last_seen"], name="idx_route_device_lastseen"),
        models.Index(fields=["network", "last_seen"], name="idx_route_network_lastseen"),
        models.Index(fields=["protocol", "last_seen"], name="idx_route_protocol_lastseen"),
        models.Index(fields=["last_seen"], name="idx_route_lastseen"),
        models.Index(fields=["first_seen"], name="idx_route_firstseen"),
    ]
```

**Note UniqueConstraint** : `vrf=NULL` est traité comme une valeur distincte par PostgreSQL — deux routes identiques avec `vrf=NULL` vs `vrf=<obj>` seront deux entrées différentes. C'est le comportement attendu.

### `clean()`

```python
def clean(self) -> None:
    super().clean()

    # Valider que outgoing_interface appartient au device
    if self.outgoing_interface and self.device:
        if self.outgoing_interface.device_id != self.device_id:
            raise ValidationError(
                {"outgoing_interface": "Interface must belong to the specified device"}
            )

    # Extraire prefix_length depuis network
    if self.network and "/" in self.network:
        try:
            self.prefix_length = int(self.network.split("/")[1])
        except (ValueError, IndexError):
            raise ValidationError({"network": f"Invalid network format: {self.network}"})

    # Initialiser last_seen si non fourni
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

### `update_or_create_entry()` — Pattern NetDB CRITIQUE

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
        existing = cls.objects.filter(
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

### Méthode principale

```python
# NAPALM get_route_to() — tous protocoles, toutes destinations
result = task.run(
    task=napalm_get,
    getters=["get_route_to"],
    getters_options={
        "get_route_to": {
            "destination": "",   # toutes les destinations
            "protocol": "",      # tous les protocoles
            "longer": False,
        }
    },
    severity_level=20,
)
routes = result.result.get("get_route_to", {})
# routes = {"10.0.0.0/8": [{"protocol": "OSPF", "next_hop": "...", ...}, ...], ...}
```

**Pas de fallback Netmiko/TextFSM** : si le driver NAPALM ne supporte pas `get_route_to()` → `Result(failed=True, result="get_route_to not supported")` + log warning + device skipped.

### Normalisation protocole

```python
protocol_normalized = entry.get("protocol", "unknown").lower()
# "OSPF" → "ospf", "BGP" → "bgp", "STATIC" → "static", etc.
```

### Gestion ECMP

Chaque next-hop dans la liste = une entrée `RouteEntry` séparée :

```python
for prefix, nexthops in routes.items():
    for nexthop in nexthops:   # ECMP : peut avoir plusieurs next-hops
        process_single_route(device, prefix, nexthop)
```

### Gestion next_hop vide

Routes CONNECTED et LOCAL retournent souvent `next_hop=""` dans NAPALM (Arista EOS notamment). Stocker la chaîne vide telle quelle.

### Préfixes exclus

```python
EXCLUDED_ROUTE_NETWORKS: tuple[str, ...] = (
    "224.0.0.0/4",     # IPv4 Multicast
    "239.0.0.0/8",     # IPv4 Multicast local
    "169.254.0.0/16",  # IPv4 Link-local
    "127.0.0.0/8",     # IPv4 Loopback
    "ff00::/8",        # IPv6 Multicast
    "fe80::/10",       # IPv6 Link-local
    "::1/128",         # IPv6 Loopback
)
```

Filtrage via `ipaddress.ip_network(prefix).overlaps(excluded_net)` ou simple `startswith` sur le prefix string.

### Résolution VRF

```python
routing_table = nexthop.get("routing_table", "default")

if routing_table and routing_table not in ("default", "inet.0", ""):
    vrf = VRF.objects.filter(name=routing_table).first()
else:
    vrf = None  # Table globale
```

### Résolution `outgoing_interface`

```python
iface_name = nexthop.get("outgoing_interface", "")
interface = None
if iface_name:
    interface = interfaces_by_name.get(iface_name)
    if not interface:
        interface = interfaces_by_name.get(normalize_interface_name(iface_name))
```

Pre-fetch avant la boucle : `interfaces_by_name = {i.name: i for i in Interface.objects.filter(device=device)}`.

---

## 3. NetDB UPDATE/INSERT Logic — Résumé algorithmique

```
Pour chaque route collectée sur un device :
  1. Normaliser le protocole en lowercase
  2. Vérifier si le préfixe est exclu (multicast, link-local) → skip
  3. Pour chaque next-hop (ECMP) :
     a. Résoudre VRF (None si table globale)
     b. Résoudre outgoing_interface (None si non trouvée)
     c. Chercher : RouteEntry.filter(device, vrf, network, next_hop, protocol).first()
     d. Si trouvé → UPDATE last_seen + champs volatils (metric, admin_distance, is_active)
     e. Si non trouvé → INSERT nouvelle entrée (first_seen = auto, last_seen = now)

Résultat :
  - Route stable pendant 90 jours → 1 seul enregistrement (first_seen initial, last_seen = dernier scan)
  - Route qui change de next-hop → nouvelle entrée INSERT (ancien next-hop expire)
  - Route ECMP (2 next-hops) → 2 entrées distinctes
```

---

## 4. Jobs

### `CollectRoutesJob(BaseCollectionJob)`

**Meta** :
```python
class Meta:
    name = "Collect Routing Tables"
    grouping = "Route Tracking"
    description = "Collect routing table entries from network devices using NAPALM"
    has_sensitive_variables = False
    soft_time_limit = 3600
    time_limit = 7200
```

**Variables** (héritées de `BaseCollectionJob`) :
- `dynamic_group`, `device`, `device_role`, `location`, `tag` (filtres)
- `workers` (IntegerVar, default=50, min=1, max=100)
- `timeout` (IntegerVar, default=30, min=10, max=300)
- `commit` (BooleanVar, default=True)
- `debug_mode` (BooleanVar, default=False)

**Workflow `run()`** :
1. `get_target_devices(device, dynamic_group, device_role, location, tag)`
2. `initialize_nornir(devices, workers, timeout)`
3. `nr.run(task=collect_routes_task)` — **SINGLE parallel call**
4. Pour chaque device (séquentiel) :
   - Vérifier `host_result.failed`
   - Si `commit` : `process_routes(device, routes_data)` → stats
   - Sinon : log DRY-RUN counts
5. Log summary
6. `RuntimeError` si `devices_success == 0 AND devices_failed > 0`

**`collect_routes_task(task)`** :
```python
def collect_routes_task(task: Task) -> Result:
    host = task.host
    try:
        result = task.run(
            task=napalm_get,
            getters=["get_route_to"],
            getters_options={"get_route_to": {"destination": "", "protocol": ""}},
            severity_level=20,
        )
        routes = result.result.get("get_route_to", {})
        return Result(host=host, result=routes)
    except NornirSubTaskError as exc:
        root_cause = _extract_nornir_error(exc)
        return Result(host=host, failed=True, result=f"get_route_to failed: {root_cause}")
    except Exception as exc:
        return Result(host=host, failed=True, result=f"Collection failed: {exc}")
```

**`process_routes(device, routes_dict)`** :
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

                    # Résoudre VRF
                    vrf = _resolve_vrf(routing_table)

                    # Résoudre interface
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

**Meta** : `name = "Purge Old Routes"`, `grouping = "Route Tracking"`

**Variables** :
- `retention_days` : IntegerVar(default=90, min_value=1, max_value=365)
- `commit` : BooleanVar(default=True)

**`run()`** :
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

**Input format critique** (tests) :
```python
# FK → liste de strings
filterset = RouteEntryFilterSet({"device": [str(device.pk)]})
filterset = RouteEntryFilterSet({"vrf": [str(vrf.pk)]})
# MultipleChoiceFilter → liste de strings
filterset = RouteEntryFilterSet({"protocol": ["ospf", "bgp"]})
# CharFilter → bare string
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

### API REST

```python
# api/serializers.py
class RouteEntrySerializer(NautobotModelSerializer):
    class Meta:
        model = RouteEntry
        fields = "__all__"

# api/views.py
class RouteEntryViewSet(NautobotModelViewSet):
    queryset = RouteEntry.objects.select_related(
        "device", "vrf", "outgoing_interface"
    ).prefetch_related("tags")
    serializer_class = RouteEntrySerializer
    filterset_class = RouteEntryFilterSet
```

Endpoints :
- `GET /api/plugins/route-tracking/routes/` — liste paginée
- `GET /api/plugins/route-tracking/routes/<uuid>/` — détail
- `POST /api/plugins/route-tracking/routes/` — créer
- `PATCH /api/plugins/route-tracking/routes/<uuid>/` — modifier
- `DELETE /api/plugins/route-tracking/routes/<uuid>/` — supprimer

### Device tab — `template_content.py`

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

### `tests/conftest.py` — Fixtures

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

### Tests prioritaires

| Fichier | Tests clés |
| ------- | ---------- |
| `test_models.py` | création, UniqueConstraint IntegrityError, clean() ValidationError, `__str__()`, UPDATE vs INSERT (update_or_create_entry) |
| `test_jobs.py` | UPDATE last_seen, INSERT new route, ECMP (2 next-hops = 2 lignes), excluded prefix skipped, PurgeOldRoutesJob |
| `test_filters.py` | device (list[str]), vrf (list[str]), protocol (list), network (icontains), q |
| `test_api.py` | GET list/detail, POST, PATCH, DELETE, unauthorized → 403 |
| `test_views.py` | list 200, detail 200, permissions |

### Mock pattern pour les jobs

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

| Paramètre | Valeur défaut | Configurable |
| --------- | ------------- | ------------ |
| Nornir workers | 50 | Oui (1-100) |
| Timeout par device | 30s | Oui (10-300s) |
| Pre-fetch interfaces | Par device avant boucle | Non (automatique) |
| Pre-fetch VRFs | Au démarrage du job | Non (automatique) |
| transaction.atomic() | Par device | Non (automatique) |

Optimisations DB :
- `select_related("device", "vrf", "outgoing_interface")` sur tous les querysets UI/API
- `prefetch_related("tags")` sur tous les querysets
- Index sur `(device, last_seen)`, `(network, last_seen)`, `(protocol, last_seen)`

---

## 8. Configuration plugin

```python
# nautobot_config.py
PLUGINS = ["nautobot_route_tracking"]
PLUGINS_CONFIG = {
    "nautobot_route_tracking": {
        "route_retention_days": 90,   # int : jours de rétention par défaut
        "nornir_workers": 50,         # int : workers Nornir par défaut
        "device_timeout": 30,         # int : timeout par device en secondes
    }
}
```

`default_settings` dans `NautobotAppConfig.__init__.py` :
```python
default_settings = {
    "route_retention_days": 90,
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

Ajouter à `nautobot_config.py` :
```python
PLUGINS = ["nautobot_route_tracking"]
PLUGINS_CONFIG = {"nautobot_route_tracking": {"route_retention_days": 90}}
```

### Migrations

```bash
nautobot-server migrate
nautobot-server collectstatic --no-input
```

### Redémarrage

```bash
# Docker
docker restart nautobot nautobot-worker nautobot-scheduler

# Docker Compose
docker compose restart nautobot nautobot-worker nautobot-scheduler
```

### Prérequis Nautobot

- Chaque device doit avoir une **Platform** avec `network_driver` configuré (ex. `cisco_ios`, `arista_eos`)
- Chaque platform doit avoir `napalm_driver` configuré (ex. `ios`, `eos`)
- Chaque device doit avoir un **SecretsGroup** avec credentials SSH
- Le plugin `nautobot-plugin-nornir` doit être installé et configuré dans `PLUGINS`

### Vérification post-installation

```bash
# Vérifier que le plugin est chargé
nautobot-server shell -c "import nautobot_route_tracking; print(nautobot_route_tracking.__version__)"

# Vérifier les migrations
nautobot-server showmigrations nautobot_route_tracking

# Vérifier les jobs
nautobot-server shell -c "from nautobot.extras.models import Job; print(Job.objects.filter(module_name__contains='route_tracking').values('name', 'enabled'))"
```
