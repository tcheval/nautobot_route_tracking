# NetDB Standards Analysis — nautobot_netdb_tracking Reference

**Generated**: 2026-02-18
**Source plugin**: `nautobot-netdb-tracking` v1.0.0
**Purpose**: Reference document for implementing `nautobot_route_tracking` following the exact same standards, patterns, and conventions.

---

## Table of Contents

1. [Code Standards](#1-code-standards)
2. [Architecture Principles](#2-architecture-principles)
3. [Pitfalls Nautobot 3.x — Complet et Verbatim](#3-pitfalls-nautobot-3x--complet-et-verbatim)
4. [Testing Patterns](#4-testing-patterns)
5. [Plugin Configuration](#5-plugin-configuration)
6. [pyproject.toml — Exact Configuration](#6-pyprojecttoml--exact-configuration)
7. [Swarm Mode Patterns](#7-swarm-mode-patterns)

---

## 1. Code Standards

Sources: `CLAUDE.md`, `SPECS.md`, `docs/nautobot_plugin_dev_lessons.md`

### 1.1 `validated_save()` vs `.save()` — Règle absolue

**Règle**: Ne jamais utiliser `.save()` directement. Toujours utiliser `.validated_save()`.

**Explication**: `validated_save()` est la méthode Nautobot qui appelle `full_clean()` puis `save()`. Elle garantit :
- L'exécution de `clean()` (validation custom du modèle)
- L'exécution des validations Django (`validate_unique`, `validate_constraints`)
- Le respect des contraintes Nautobot (custom fields, tags, etc.)

```python
# JAMAIS
mac.save()
MACAddressHistory.objects.create(...)

# TOUJOURS
mac.validated_save()

# Pattern update_or_create_entry (NetDB logic)
instance = MACAddressHistory(device=device, interface=interface, ...)
instance.validated_save()
```

**Exception connue**: Le champ `grouping` d'un Job est écrasé par `validated_save()`. Pour le modifier, utiliser `QuerySet.update()` :

```python
Job.objects.filter(module_name__startswith="nautobot_netdb_tracking").update(
    enabled=True, grouping="NetDB Tracking"
)
```

**Règle dans les fixtures de test**: Les fixtures doivent aussi utiliser `validated_save()`, pas `.create()` ni `.save()`, pour exercer les mêmes validations qu'en production.

### 1.2 Type Hints — Obligatoires, format Python 3.10+

**Format obligatoire** : Python 3.10+ native syntax (PEP 604).

```python
# Python 3.10+ — utiliser ces formes
def get_devices(filters: dict[str, Any]) -> list[Device]: ...
def find_mac(mac: str | None) -> MACAddressHistory | None: ...
def process_results(device: Device, entries: list[dict]) -> dict[str, int]: ...

# INTERDIT — ancien style Optional
from typing import Optional
def find_mac(mac: Optional[str]) -> Optional[MACAddressHistory]: ...
```

**Règles**:
- Annoter tous les paramètres et retours de fonctions publiques
- Utiliser `TypedDict` pour les structures de données complexes passées en dict
- Utiliser `typing.Protocol` plutôt que l'héritage pour le duck typing
- Importer `Any` depuis `typing` quand nécessaire

### 1.3 Docstrings — Style Google, sections obligatoires

**Style**: Google style docstrings sur toutes les fonctions/classes publiques.

```python
def process_mac_results(device: Device, mac_entries: list[dict]) -> dict[str, int]:
    """Process collected MAC entries and apply NetDB UPDATE/INSERT logic.

    Args:
        device: Nautobot Device instance
        mac_entries: List of dicts with keys: interface, mac, vlan

    Returns:
        Dict with stats: {"updated": int, "created": int, "errors": int}

    Raises:
        ValidationError: If MAC format invalid or interface not found

    Example:
        >>> result = process_mac_results(device, [{"mac": "00:11:22:33:44:55", ...}])
        >>> print(result)
        {'updated': 5, 'created': 2, 'errors': 0}

    """
```

**Sections obligatoires selon le contexte**:
- `Args`: toujours si la fonction a des paramètres
- `Returns`: toujours si la fonction retourne quelque chose (sauf `None`)
- `Raises`: si des exceptions peuvent être levées
- `Example`: pour les fonctions utilitaires importantes

**Modules et classes**: docstring obligatoire. Packages (`__init__.py`): facultatif (D104 ignoré dans ruff).

### 1.4 Error Handling — Patterns recommandés

**Règle principale**: Ne jamais attraper `Exception` nu sans logger. Cibler l'exception spécifique.

```python
# INTERDIT — exception avalée silencieusement
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    pass

# CORRECT — log l'erreur, puis continue
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    host.logger.warning("MAC collection subtask failed", exc_info=True)

# CORRECT — exception spécifique + log + raise ou return
try:
    device = Device.objects.get(name=device_name)
except Device.DoesNotExist:
    self.logger.error("Device %s not found", device_name)
    return None
```

**Pattern dans les Jobs** : try/except par device pour que l'échec d'un device ne crash pas le job entier :

```python
for device_name, device_obj in device_map.items():
    try:
        host_result = results[device_name]
        if host_result.failed:
            stats["failed"] += 1
            continue
        if commit:
            self.process_results(device_obj, host_result.result)
            stats["success"] += 1
    except Exception as e:
        stats["failed"] += 1
        self.logger.error(
            "Failed: %s",
            e,
            extra={"grouping": device_name},
        )
```

**Règle RuntimeError sur les Jobs** : ne raise `RuntimeError` que si TOUS les devices ont échoué :

```python
# MAUVAIS — 3 devices down sur 1500 = job FAILURE
if self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

# BON — FAILURE uniquement si panne infra globale
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)
```

**Exceptions custom** : hériter d'une base exception du projet. Logger AVANT de re-raise.

### 1.5 Logging — Format et structured logging

**Règle de base** : `logging.getLogger(__name__)` systématiquement. Ne jamais utiliser `print()`.

```python
import logging
logger = logging.getLogger(__name__)
```

**Niveaux** :
- `DEBUG` : flux détaillé (valeurs intermédiaires, boucles)
- `INFO` : opérations métier normales (device collecté, entrée créée)
- `WARNING` : dégradé acceptable (device injoignable sur 1500, fallback activé)
- `ERROR` : échec d'une opération (device skip, DB error)

**Format des messages** : lazy formatting `%s`/`%d` dans les appels logger (pas de f-string) :

```python
# BON — lazy formatting (pas évalué si level désactivé)
logger.info("Device %s: interface %s updated", device.name, intf.name)
logger.error("Collection failed for %s: %s", device_name, error_msg)

# INTERDIT dans logger.* (mais OK ailleurs)
logger.info(f"Device {device.name} updated")  # f-string évalué même si DEBUG désactivé
```

**Structured logging avec `extra={"grouping": ...}`** (Nautobot Jobs) :

```python
# Dans les Jobs Nautobot — grouper les logs par device
self.logger.info(
    "Collected %d MACs",
    mac_count,
    extra={"grouping": device.name},
)
self.logger.error(
    "Collection failed: %s",
    error_msg,
    extra={"grouping": device_name},
)
self.logger.info(
    "Completed: %d success, %d failed",
    stats["success"],
    stats["failed"],
    extra={"grouping": "summary"},
)
```

**Règle `%` vs f-string** : Ruff UP031 signale `%` en dehors des appels logger. Utiliser f-string partout sauf dans les appels `logger.*` :

```python
# MAUVAIS (UP031) hors logger
summary = "Completed in %.1fs" % elapsed

# BON hors logger
summary = f"Completed in {elapsed:.1f}s"

# BON dans logger (garder le lazy %s)
logger.info("Completed in %.1fs", elapsed)
```

### 1.6 Nommage

- `snake_case` pour fonctions/variables/modules
- `PascalCase` pour classes
- `UPPER_SNAKE_CASE` pour constantes
- Préfixer `_` les fonctions/méthodes internes non exposées
- Noms explicites : `device_queryset` plutôt que `qs`, `interface_count` plutôt que `cnt`

### 1.7 Django ORM — Règles

```python
# JAMAIS de requête dans une boucle
for mac in MACAddressHistory.objects.all():
    print(mac.device.name)  # N+1 queries

# TOUJOURS select_related / prefetch_related
for mac in MACAddressHistory.objects.select_related("device", "interface"):
    print(mac.device.name)  # 1 query

# .exists() plutôt que len() ou bool()
if queryset.exists():  # BON
if len(queryset) > 0:  # MAUVAIS

# .count() plutôt que len()
count = queryset.count()  # BON (DB-side)
count = len(queryset)     # MAUVAIS (Python-side, charge tous les objets)

# Agréger côté DB
from django.db.models.functions import TruncDate
mac_counts = dict(
    MACAddressHistory.objects.filter(first_seen__gte=start_date)
    .annotate(date=TruncDate("first_seen"))
    .values("date")
    .annotate(count=Count("id"))
    .values_list("date", "count")
)
```

### 1.8 Modèles Django — Standards

- Chaque modèle a un `__str__` explicite et utile
- `Meta.ordering` par défaut quand pertinent
- `Meta.constraints` et `Meta.indexes` plutôt que validation ad-hoc
- Pas de logique métier dans les modèles au-delà de `clean()` — la logique métier va dans des services ou fonctions dédiées
- Les ForeignKey ont toujours un `related_name` explicite et un `on_delete` réfléchi
- Tout champ nullable justifie pourquoi `null=True` est nécessaire

---

## 2. Architecture Principles

Source: `CLAUDE.md`, `docs/architecture.md`

### 2.1 Principes fondamentaux

Le plugin suit strictement les [Network-to-Code best practices](https://github.com/nautobot/cookiecutter-nautobot-app) :

1. **`validated_save()` TOUJOURS** — jamais `.save()` directement
2. **Structured Logging** — `self.logger.info(..., extra={"grouping": device.name})`
3. **Error Handling** — dégradation gracieuse, un device en échec ne crash pas le job entier
4. **Transactions** — `transaction.atomic()` pour les opérations DB
5. **Type Hints** — Python 3.10+ type hints partout

### 2.2 NEVER Degrade Production Code for Test Infrastructure (CRITIQUE)

**Règle absolue** : Le code de production suit les standards industriels. Si un outil de test (FakeNOS, mock, simulateur) ne se comporte pas correctement, le problème est l'outil de test — pas le code de production.

Ne jamais :
- Ajouter des branches `if fakenos:` dans le code du job
- Skipper NAPALM pour aller directement à Netmiko parce que FakeNOS retourne des données incorrectes depuis les getters NAPALM
- Assouplir la validation ou le error handling pour tolérer des données de test incorrectes
- Tout hack "temporaire" qui dégrade le flow de collecte standard (NAPALM d'abord → fallback Netmiko/TextFSM)

L'approche correcte est **toujours** de corriger l'infrastructure de test (config FakeNOS, mock data, réponses simulateur) pour qu'elle se comporte comme du vrai équipement.

### 2.3 Séparation des responsabilités

```
nautobot_<plugin>/
├── __init__.py           # NautobotAppConfig — configuration uniquement
├── models.py             # Modèles + validation + update_or_create_entry
├── views.py              # Vues UI — pas de logique métier
├── filters.py            # FilterSets — filtrage uniquement
├── tables.py             # Tables django-tables2 — affichage uniquement
├── forms.py              # Formulaires — validation input utilisateur
├── urls.py               # Routing uniquement
├── navigation.py         # Menu — déclaratif uniquement
├── template_content.py   # Extensions de templates Nautobot
├── signals.py            # Handlers post_migrate + utilitaires purge
├── admin.py              # Admin Django
├── api/
│   ├── serializers.py    # Serializers DRF
│   ├── views.py          # API ViewSets
│   └── urls.py           # Routes API
└── jobs/
    ├── __init__.py       # register_jobs() — OBLIGATOIRE
    ├── _base.py          # BaseCollectionJob (abstract) + utilitaires partagés
    ├── collect_*.py      # Jobs de collecte spécifiques
    └── purge_*.py        # Job de purge
```

**Règle de responsabilité** :
- `models.py` : source de vérité pour les fonctions de normalisation (DRY)
- `jobs/_base.py` : code partagé entre les jobs (évite les imports circulaires)
- `signals.py` : uniquement les handlers de signaux et les fonctions de purge programmatique
- Pas de logique métier dans les vues, serializers, ou templates

### 2.4 Ce qui ne doit jamais être dégradé

| Principe | Règle |
| -------- | ----- |
| `validated_save()` | Jamais contourné, même dans les tests |
| NetDB UPDATE/INSERT logic | `update_or_create_entry()` toujours utilisé, jamais de simple `create()` |
| Error isolation par device | try/except par device dans la boucle de traitement |
| Parallel collection | `nr.run()` unique sur tous les hosts, jamais en boucle sérielle |
| Secrets via Nautobot | Jamais hardcodé, toujours via `CredentialsNautobotSecrets` |

### 2.5 Héritage des classes de base Nautobot

| Composant | Classe parente | Source |
| --------- | -------------- | ------ |
| Modèles business | `PrimaryModel` | `nautobot.apps.models` |
| Modèles organisationnels | `OrganizationalModel` | `nautobot.apps.models` |
| UI ViewSets | `NautobotUIViewSet` | `nautobot.apps.views` |
| API ViewSets | `NautobotModelViewSet` | `nautobot.apps.views` |
| Serializers | `NautobotModelSerializer` | `nautobot.apps.api.serializers` |
| FilterSets | `NautobotFilterSet` | `nautobot.apps.filters` |
| Model Forms | `NautobotModelForm` | `nautobot.apps.forms` |
| Filter Forms | `NautobotFilterForm` | `nautobot.apps.forms` |
| Tables | `BaseTable` | `nautobot.apps.tables` |
| Template Extensions | `TemplateExtension` | `nautobot.apps.ui` |
| Jobs | `Job` | `nautobot.apps.jobs` (Nautobot 3.x) |
| App Config | `NautobotAppConfig` | `nautobot.apps` |

Ne jamais hériter directement de `django.db.models.Model` ou des classes DRF brutes.

---

## 3. Pitfalls Nautobot 3.x — Complet et Verbatim

Source: `docs/nautobot_plugin_dev_lessons.md` — reproduit intégralement pour réutilisation dans le nouveau plugin.

---

### 3.1 Nornir et parallélisme

#### Pattern golden-config (REFERENCE)

Le pattern de référence est celui de [nautobot-app-golden-config](https://github.com/nautobot/nautobot-app-golden-config/tree/v3.0.2/nautobot_golden_config/nornir_plays). Tout job Nornir doit le suivre.

**Correct** : un seul `nr.run()` sur tous les hosts en parallèle.

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

#### Erreurs à ne JAMAIS faire

| Anti-pattern | Pourquoi c'est mauvais |
| ------------ | ---------------------- |
| Boucle sérielle de reachability check AVANT `nr.run()` | Defeat le parallélisme. Un check TCP par device = N * 5s en série |
| `nr.filter(name=device_name).run()` dans une boucle | Idem — exécution séquentielle déguisée |
| Retry logic après `nr.run()` avec `time.sleep()` | Bloque tout le job. Nornir gère les timeouts nativement |
| `tenacity` retry decorator sur `_collect_from_host()` | Complexité inutile. Si un device fail, il fail — on log et on continue |
| `_collect_from_host()` per-device method | Dead code quand on utilise `_combined_*_task` avec `nr.run()` |

#### Task combinée (pattern correct)

Pour collecter plusieurs types de données sur un même host dans une seule session SSH :

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

#### NornirSubTaskError : extraction de la root cause (CRITIQUE)

Quand `task.run()` échoue (SSH timeout, connection refused, auth failure), Nornir raise `NornirSubTaskError`. L'attribut `exc.result` est un **`MultiResult`** (liste de `Result`), PAS un `Result` unique. Accéder à `exc.result.exception` ne fonctionne jamais car les listes n'ont pas d'attribut `.exception`.

```python
# MAUVAIS — exc.result est une liste, .exception n'existe pas
# Fallback sur str(exc) = "Subtask: collect_mac_table_task (failed)"
except NornirSubTaskError as exc:
    root_cause = (
        exc.result.exception
        if hasattr(exc.result, "exception") and exc.result.exception
        else exc  # ← toujours ce branch, message générique inutile
    )

# BON — itérer le MultiResult pour trouver le Result failed
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

# Utilisation
except NornirSubTaskError as exc:
    root_cause = _extract_nornir_error(exc)
    # → "TCP connection to device failed. Common causes: ..."
```

#### Job partiel : ne pas raise RuntimeError sur devices_failed > 0

Un job de collecte sur 1500 devices aura inévitablement quelques échecs (maintenance, panne, ACL). Marquer le job entier comme FAILURE empêche le monitoring de distinguer un vrai problème d'un fonctionnement normal.

```python
# MAUVAIS — 3 devices down sur 1500 = job FAILURE + RuntimeError dans Celery
if self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

# BON — FAILURE uniquement si AUCUN device n'a réussi (panne infra globale)
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

return {
    "success": self.stats["devices_failed"] == 0,  # True si 100% success
    "summary": summary_msg,
    **self.stats,
}
```

| Scénario | Avant | Après |
| -------- | ----- | ----- |
| 1500/1500 OK | SUCCESS | SUCCESS |
| 1497/1500 OK, 3 down | FAILURE + RuntimeError | SUCCESS (success=False dans result) |
| 0/1500 OK (panne infra) | FAILURE + RuntimeError | FAILURE + RuntimeError |

#### Mocking Nornir dans les tests

Toujours mocker `nr.run()` directement, jamais `nr.filter().run()` ni `_collect_from_host` :

```python
@patch("nautobot_netdb_tracking.jobs._base.InitNornir")
@patch("nautobot_netdb_tracking.jobs._base.NautobotORMInventory", None)
def test_job_commit_mode(self, mock_init_nornir, device_with_platform, interface):
    mock_nr = MagicMock()
    mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}
    mock_init_nornir.return_value = mock_nr

    # Mock nr.run() — PAS nr.filter().run()
    mock_host_result = MagicMock()
    mock_host_result.failed = False
    mock_host_result.result = {"mac_table": [...], "arp_table": [...]}
    mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

    job = CollectMACARPJob()
    job.logger = MagicMock()
    result = job.run(...)
```

---

### 3.2 NautobotORMInventory et NAPALM

#### Problème : network_driver != napalm_driver

`NautobotORMInventory` utilise `Platform.network_driver` (ex: `arista_eos`) pour `host.platform`. Mais NAPALM attend `Platform.napalm_driver` (ex: `eos`). Sans correction, NAPALM échoue à trouver le bon driver.

#### Problème : les extras host-level écrasent les defaults

Les extras configurés par host dans `NautobotORMInventory` (via config context) **remplacent** les defaults passés à InitNornir, au lieu de les merger. On perd donc `transport`, `timeout`, etc.

#### Solution : injection post-init

Après `InitNornir()`, boucler sur les hosts pour :

1. Setter `napalm_opts.platform` depuis `Platform.napalm_driver`
2. Merger `Platform.napalm_args` dans `napalm_opts.extras.optional_args`

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

#### Config context pour le port SSH

Le port SSH custom doit être dans le config context du device, sous la clé `nautobot_plugin_nornir.connection_options` :

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

Nécessite `use_config_context.connection_options: True` dans `PLUGINS_CONFIG["nautobot_plugin_nornir"]`.

---

### 3.3 Nautobot 3.x — Modèles et ORM

#### IPAddress : champs renommés depuis Nautobot 2.x

| Nautobot 2.x | Nautobot 3.x | Notes |
| ------------ | ------------ | ----- |
| `address="10.0.0.1/24"` | `host="10.0.0.1"` + `mask_length=24` | Séparé en deux champs |
| `namespace=ns` | `parent=prefix` | Le namespace est porté par le Prefix |

Erreurs fréquentes :
- `FieldError: Invalid field name(s) for model IPAddress: 'namespace'` → utiliser `parent=prefix`
- `FieldError: ... 'address'` → utiliser `host` + `mask_length`

Création correcte en Nautobot 3.x :
```python
prefix = Prefix.objects.get(prefix="172.28.0.0/24")
ip = IPAddress(host="172.28.0.10", mask_length=24, status=active, parent=prefix, type="host")
ip.validated_save()
```

#### Job.grouping écrasé par validated_save()

Le champ `grouping` d'un Job est écrasé par `validated_save()`. Utiliser `QuerySet.update()` :

```python
Job.objects.filter(module_name__startswith="nautobot_netdb_tracking").update(
    enabled=True, grouping="NetDB Tracking"
)
```

#### validated_save() TOUJOURS

Jamais `.save()` ni `objects.create()`. Toujours `instance.validated_save()` ou le pattern `update_or_create_entry` custom.

#### select_related / prefetch_related

Jamais de queryset dans une boucle. Pre-fetch :

```python
# MAUVAIS — N+1 queries
for mac in MACAddressHistory.objects.all():
    print(mac.device.name)

# BON — 1 query
for mac in MACAddressHistory.objects.select_related("device", "interface"):
    print(mac.device.name)
```

#### Cable : Status obligatoire en Nautobot 3.x

En Nautobot 3.x, le modèle Cable **exige** un Status. Sans ça, `validated_save()` lève une `ValidationError`. Toujours récupérer le Status "Connected" avant de créer un Cable :

```python
# MAUVAIS — ValidationError: Status is required
cable = Cable(
    termination_a=interface_a,
    termination_b=interface_b,
)
cable.validated_save()

# BON
from nautobot.extras.models import Status

cable_status = Status.objects.get_for_model(Cable).get(name="Connected")
cable = Cable(
    termination_a=interface_a,
    termination_b=interface_b,
    status=cable_status,
)
cable.validated_save()
```

#### UniqueConstraint : convention de nommage

Les noms de `UniqueConstraint` doivent utiliser le préfixe `%(app_label)s_%(class)s_` pour éviter les collisions entre plugins :

```python
# MAUVAIS — risque de collision avec d'autres plugins
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["device", "interface", "mac_address", "vlan"],
            name="unique_mac_entry"
        )
    ]

# BON — préfixe unique par app/model
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["device", "interface", "mac_address", "vlan"],
            name="%(app_label)s_%(class)s_unique_mac_entry"
        )
    ]
```

#### natural_key_field_lookups pour les modèles

Les modèles Nautobot 3.x doivent définir `natural_key_field_lookups` dans leur Meta pour le support des natural keys dans l'API et les filtres. Sans ça, les lookups par natural key échouent silencieusement :

```python
class MACAddressHistory(PrimaryModel):
    class Meta:
        natural_key_field_lookups = {
            "device__name": "device",
            "interface__name": "interface",
            "mac_address": "mac_address",
        }
```

#### Race condition : count() puis delete()

Le pattern `count()` suivi de `delete()` est non-atomique. Un autre processus peut modifier les données entre les deux appels. Utiliser la valeur de retour de `delete()` :

```python
# MAUVAIS — race condition, le count peut ne pas correspondre au delete
count = queryset.filter(last_seen__lt=cutoff).count()
queryset.filter(last_seen__lt=cutoff).delete()
stats["deleted"] = count

# BON — atomique, pas de fenêtre de race
deleted_count, _ = queryset.filter(last_seen__lt=cutoff).delete()
stats["deleted"] = deleted_count
```

---

### 3.4 Nautobot 3.x — Jobs

#### Enregistrement des jobs (OBLIGATOIRE)

`jobs/__init__.py` DOIT appeler `register_jobs()`. Sans ça, les jobs sont importables mais n'apparaissent pas dans l'UI :

```python
from nautobot.core.celery import register_jobs
from myapp.jobs.my_job import MyJob

jobs = [MyJob]
register_jobs(*jobs)
```

#### ScriptVariable : accès aux attributs

Les defaults et contraintes sont dans `field_attrs`, pas en attributs directs :

```python
# MAUVAIS
job.retention_days.default  # AttributeError
job.retention_days.min_value  # AttributeError

# BON
job.retention_days.field_attrs["initial"]  # 90
job.retention_days.field_attrs["min_value"]  # 1
job.commit.field_attrs["initial"]  # True
```

#### Plugin registration en test

`test_settings.py` a besoin des DEUX :

```python
PLUGINS = ["nautobot_netdb_tracking"]           # pour nautobot-server (CI)
INSTALLED_APPS.append("nautobot_netdb_tracking")  # pour pytest-django
```

`django.setup()` ne traite PAS `PLUGINS`. `nautobot-server` ne lit PAS `DJANGO_SETTINGS_MODULE`.

#### CI : migrations

Utiliser `nautobot-server init` puis ajouter le plugin, pas `django-admin` :

```yaml
- name: Initialize Nautobot configuration
  run: |
    poetry run nautobot-server init
    echo 'PLUGINS = ["nautobot_netdb_tracking"]' >> ~/.nautobot/nautobot_config.py
- name: Run migrations
  run: poetry run nautobot-server makemigrations nautobot_netdb_tracking
```

`django-admin` ne traite pas `PLUGINS`. `nautobot-server` ne lit pas `DJANGO_SETTINGS_MODULE`.

---

### 3.5 Nautobot 3.x — API et Serializers

#### select_related dans les ViewSets API

Les `NautobotModelViewSet` doivent inclure **tous** les champs FK utilisés par le serializer dans `select_related()`. Sinon, chaque objet sérialisé génère des requêtes supplémentaires (N+1) :

```python
# MAUVAIS — ip_address_object est dans le serializer mais pas dans select_related
class ARPEntryViewSet(NautobotModelViewSet):
    queryset = ARPEntry.objects.select_related(
        "device", "device__location", "interface",
    ).prefetch_related("tags")

# BON — tous les FK du serializer sont pré-chargés
class ARPEntryViewSet(NautobotModelViewSet):
    queryset = ARPEntry.objects.select_related(
        "device", "device__location", "interface", "ip_address_object",
    ).prefetch_related("tags")
```

**Règle** : pour chaque champ FK dans le `fields` du serializer, vérifier qu'il est dans `select_related()` du ViewSet correspondant (UI et API).

#### Nested serializers : ne pas créer de code mort

Ne pas déclarer de serializers "nested" ou "lite" par anticipation. Un serializer non-importé nulle part est du code mort :

```python
# MAUVAIS — serializer déclaré mais jamais utilisé
class MACAddressHistoryNestedSerializer(NautobotModelSerializer):
    class Meta:
        model = MACAddressHistory
        fields = ["id", "url", "display", "mac_address", "last_seen"]

# BON — ne créer que ce qui est effectivement utilisé
# Si un nested serializer devient nécessaire, le créer à ce moment-là
```

---

### 3.6 Nautobot 3.x — Tests

#### FilterSet : format des inputs (CRITIQUE)

| Type de filtre | Format attendu | Exemple |
| -------------- | -------------- | ------- |
| `NaturalKeyOrPKMultipleChoiceFilter` (FK) | Liste de strings | `{"device": [str(device.pk)]}` |
| `CharFilter` | String simple | `{"mac_address": "00:11:22"}` |

```python
# MAUVAIS — bare value pour les filtres FK
filterset = MACAddressHistoryFilterSet({"device": device.pk})
filterset = MACAddressHistoryFilterSet({"device": device.name})

# BON — wrapper les valeurs FK/PK dans une liste de strings
filterset = MACAddressHistoryFilterSet({"device": [str(device.pk)]})
filterset = MACAddressHistoryFilterSet({"device": [device.name]})

# BON — les CharFilter utilisent des strings simples (pas de liste)
filterset = MACAddressHistoryFilterSet({"mac_address": "00:11:22"})
filterset = MACAddressHistoryFilterSet({"q": "search term"})
```

#### NaturalKeyOrPKMultipleChoiceFilter : to_field_name

`NaturalKeyOrPKMultipleChoiceFilter` utilise `to_field_name="name"` par défaut. Mais certains modèles Nautobot n'ont pas de champ `name` — par exemple `IPAddress` qui utilise `host` :

```python
# MAUVAIS — FieldError: Cannot resolve keyword 'name' into field
ip_address_object = NaturalKeyOrPKMultipleChoiceFilter(
    queryset=IPAddress.objects.all(),
    label="IPAM IP Address",
)

# BON — spécifier le bon champ de lookup
ip_address_object = NaturalKeyOrPKMultipleChoiceFilter(
    queryset=IPAddress.objects.all(),
    to_field_name="host",
    label="IPAM IP Address",
)
```

**Règle** : toujours vérifier que le modèle cible a un champ `name`. Sinon, spécifier `to_field_name` explicitement.

#### BaseTable : pas de configure()

Nautobot `BaseTable` n'a PAS de méthode `configure(request)`. Ne jamais l'appeler :

```python
# MAUVAIS — AttributeError
table = MACAddressHistoryTable(data)
table.configure(request)

# BON
table = MACAddressHistoryTable(data)
```

Les cellules null FK peuvent render en `&mdash;` (HTML entity), pas juste `—` ou `""` :

```python
# MAUVAIS — strict string match pour les cellules null
assert str(cell) in ["", "—", "-"]

# BON — account for HTML entity rendering
assert cell is None or "—" in str(cell) or "&mdash;" in str(cell) or str(cell) in ["", "-"]
```

#### Tab view templates : render_table et obj_table.html

`{% render_table table %}` sans argument template utilise le `DJANGO_TABLES2_TEMPLATE` de Nautobot (`utilities/obj_table.html`). Ce template accède à `table.context` qui n'existe que si la table a été configurée via `RequestConfig`. Les tab views créent des tables sans `RequestConfig` → crash `AttributeError: object has no attribute 'context'`.

```django
{# MAUVAIS — crash sur les tab views #}
{% render_table table %}

{# BON — force un template simple qui ne requiert pas table.context #}
{% render_table table "django_tables2/bootstrap5.html" %}
```

#### test_settings.py : CACHES doit inclure TIMEOUT

```python
# MAUVAIS
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://localhost:6379/0",
    }
}

# BON
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": "redis://localhost:6379/0",
        "TIMEOUT": 300,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}
```

#### Nautobot 3.x export : ExportTemplate obligatoire

Nautobot 3.x utilise des objets `ExportTemplate` pour l'export CSV/YAML. Sans `ExportTemplate` configurée, une requête `?export=csv` retourne **404** (pas un CSV vide ni une erreur 500) :

```python
# BON — tester que l'export sans template renvoie 404
def test_export_without_template(self, authenticated_client):
    url = reverse("plugins:myapp:mymodel_list")
    response = authenticated_client.get(url, {"export": "csv"})
    assert response.status_code == 404
```

#### API test URLs : reverse() vs hardcoded paths

`reverse()` avec des namespaces imbriqués est fragile dans les environnements de test. Solution fiable : utiliser des chemins URL hardcodés dans les tests API :

```python
# MAUVAIS — NoReverseMatch si le namespace n'est pas correctement injecté
url = reverse("plugins-api:nautobot_netdb_tracking-api:macaddresshistory-list")

# BON — fiable, pas de dépendance au resolver
_API_BASE = "/api/plugins/netdb-tracking"

def _mac_list_url():
    return f"{_API_BASE}/mac-address-history/"

def _mac_detail_url(pk):
    return f"{_API_BASE}/mac-address-history/{pk}/"
```

#### conftest.py : utiliser validated_save()

Les fixtures de test doivent utiliser `validated_save()`, pas `.create()` ni `.save()` :

```python
# MAUVAIS — contourne les validations du modèle
@pytest.fixture
def mac_entry(device, interface):
    return MACAddressHistory.objects.create(
        device=device, interface=interface, mac_address="AA:BB:CC:DD:EE:FF",
        last_seen=timezone.now()
    )

# BON — valide les contraintes et clean()
@pytest.fixture
def mac_entry(device, interface):
    entry = MACAddressHistory(
        device=device, interface=interface, mac_address="AA:BB:CC:DD:EE:FF",
        last_seen=timezone.now()
    )
    entry.validated_save()
    return entry
```

#### Couverture de tests : zones souvent oubliées

| Zone à tester | Pourquoi |
| ------------- | -------- |
| Forms (`NautobotModelForm`, `NautobotFilterForm`) | Valider les `query_params`, `required`, widgets, et la méthode `clean()` |
| TemplateExtension (`template_content.py`) | Vérifier le rendu HTML, les contextes, et les requêtes N+1 dans les panels |
| Permissions sur les vues custom | Vérifier que les vues non-NautobotUIViewSet renvoient 403/302 pour les anonymes |
| CI test job actif | Le job de test dans `.github/workflows/ci.yml` ne doit jamais être commenté |

#### Tests de permissions sur les vues

```python
def test_dashboard_requires_login(client):
    """Verify anonymous users are redirected to login."""
    response = client.get("/plugins/netdb-tracking/dashboard/")
    assert response.status_code == 302
    assert "/login/" in response.url

def test_dashboard_requires_permission(authenticated_client):
    """Verify permission check is enforced."""
    response = authenticated_client.get("/plugins/netdb-tracking/dashboard/")
    assert response.status_code == 403
```

---

### 3.7 Django — Vues et Templates

#### Mixins d'authentification

Les vues custom (non-NautobotUIViewSet) DOIVENT avoir les mixins auth :

```python
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin

class NetDBDashboardView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_macaddresshistory"
```

`NautobotUIViewSet` gère l'auth automatiquement. Les `View` Django standard ne le font PAS.

**Attention aux tab views** : chaque `permission_required` doit correspondre au modèle affiché par la vue, pas une permission générique commune à toutes les vues :

```python
# MAUVAIS — accessible sans authentification
class DeviceMACTabView(View):
    def get(self, request, pk): ...

# BON — auth + permissions model-specific
class DeviceMACTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_macaddresshistory"

class DeviceARPTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_arpentry"

class DeviceTopologyTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_topologyconnection"
```

#### QueryDict.pop() vs getlist()

`QueryDict.pop(key)` retourne la **dernière valeur** (un string unique), pas une liste. Pour les paramètres multi-valeur, utiliser `request.GET.getlist()` :

```python
# MAUVAIS — retourne "uuid2" (string), pas ["uuid1", "uuid2"]
devices = request.GET.pop("device", None)

# BON — retourne ["uuid1", "uuid2"]
devices = request.GET.getlist("device")
```

#### Template tags

Les filtres Django externes nécessitent un `{% load %}` explicite :

```django
{# MAUVAIS — TemplateSyntaxError #}
{% load helpers %}
{{ value|intcomma }}

{# BON #}
{% load helpers humanize %}
{{ value|intcomma }}
```

#### Nautobot UI Template Standards (CRITIQUE)

Tous les templates de plugin DOIVENT suivre les patterns natifs Nautobot.

**Table rendering** — TOUJOURS utiliser `inc/table.html` (vues NautobotUIViewSet) :

```django
{# MAUVAIS — django_tables2 default template, mauvais style de pagination #}
{% render_table table "django_tables2/bootstrap5.html" %}

{# BON — template standard de Nautobot, utilisé par toutes les vues core #}
{% render_table table "inc/table.html" %}
```

**Pagination** — TOUJOURS utiliser `inc/paginator.html` avec `EnhancedPaginator` :

```python
# MAUVAIS — paginator Django par défaut
RequestConfig(request, paginate={"per_page": 50}).configure(table)

# BON — EnhancedPaginator de Nautobot
from nautobot.core.views.paginator import EnhancedPaginator, get_paginate_count

per_page = get_paginate_count(request)
RequestConfig(
    request,
    paginate={"per_page": per_page, "paginator_class": EnhancedPaginator},
).configure(table)
```

```django
{# Dans le template, après la card de table #}
{% include 'inc/paginator.html' with paginator=table.paginator page=table.page %}
```

**Page titles** — JAMAIS créer un `<h1>` en doublon :

```django
{# MAUVAIS — base_django.html rend déjà {% block title %} comme <h1> #}
{% block title %}My Page{% endblock %}
{% block content %}
<h1>My Page</h1>  {# DOUBLON — crée deux <h1> sur la page #}
{% endblock %}

{# BON — laisser Nautobot gérer le <h1> via {% block title %} uniquement #}
{% block title %}My Page{% endblock %}
{% block content %}
{# Pas de <h1> ici #}
{% endblock %}
```

**Breadcrumbs** — uniquement sur les pages de détail (niveau 2) :

```django
{# MAUVAIS — breadcrumbs sur les pages list/report #}
{% block breadcrumbs %}
<li class="breadcrumb-item"><a href="...">Parent</a></li>
<li class="breadcrumb-item active">Current Page</li>
{% endblock %}

{# BON — breadcrumbs vides sur les pages list/report #}
{% block breadcrumbs %}{% endblock %}
```

**`{% load %}` syntax** — lignes séparées pour les différentes librairies :

```django
{# MAUVAIS — Django parse "from" et charge helpers/humanize depuis django_tables2 #}
{% load helpers humanize render_table from django_tables2 %}

{# BON — load statements séparés #}
{% load helpers humanize %}
{% load render_table from django_tables2 %}
```

---

### 3.8 Vues custom avec filter sidebar et pagination

Quand on crée une page custom (pas un `NautobotUIViewSet`) mais qu'on veut le look natif Nautobot, il y a 5 pièges majeurs :

#### Piège 1 : `generic/object_list.html` est couplé à NautobotUIViewSet

Ne PAS étendre `generic/object_list.html` pour une vue custom. Ce template est fortement couplé au contexte fourni par `NautobotHTMLRenderer`. **Solution** : étendre `base.html`.

#### Piège 2 : `BaseTable` requiert un `Meta.model`

`BaseTable.__init__` appelle `CustomField.objects.get_for_model(model)`. Si `Meta.model` est `None` (table basée sur des dicts), ça crash.

**Solution** : utiliser `django_tables2.Table` au lieu de `BaseTable` :

```python
import django_tables2 as tables

class MyCustomTable(tables.Table):  # PAS BaseTable !
    col1 = tables.Column()

    class Meta:
        template_name = "django_tables2/bootstrap5.html"  # OBLIGATOIRE
        attrs = {"class": "table table-hover nb-table-headings"}
        fields = ("col1",)
```

#### Piège 3 : le template django-tables2 par défaut est un template Nautobot custom

`DJANGO_TABLES2_TEMPLATE` est configuré sur `utilities/obj_table.html` dans Nautobot. Ce template accède à `table.data.verbose_name_plural`, `permissions.change`, etc. — tout ça est absent pour une `tables.Table` avec des dicts.

**Solution** : forcer `template_name = "django_tables2/bootstrap5.html"` dans `Meta`.

#### Piège 4 : `{% filter_form_drawer %}` a 4 args positionnels obligatoires

```django
{# MAUVAIS — TemplateSyntaxError: did not receive value(s) for 'filter_params' #}
{% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title %}

{# BON #}
{% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title filter_params=filter_params %}
```

La vue DOIT passer `dynamic_filter_form` (= `None`) et `filter_params` (= `[]`) dans le contexte.

#### Piège 5 : `{% load X Y Z from library %}` charge X, Y, Z depuis library

```django
{# MAUVAIS — Django cherche "helpers" et "humanize" dans django_tables2 #}
{% load helpers humanize render_table from django_tables2 %}

{# BON — load séparément #}
{% load helpers humanize %}
{% load render_table from django_tables2 %}
```

#### Pattern complet — Vue

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
        all_data = [{"col1": "a", "col2": "b"}, ...]
        table = MyCustomTable(all_data)
        per_page = request.GET.get("per_page", 50)
        RequestConfig(request, paginate={"per_page": per_page}).configure(table)

        return render(request, self.template_name, {
            "table": table,
            "filter_form": filter_form,
            "dynamic_filter_form": None,   # requis par filter_form_drawer
            "filter_params": [],            # requis par filter_form_drawer
            "title": "My Page",
            "permissions": {"add": False, "change": False, "delete": False, "view": True},
            "action_buttons": (),
            "content_type": None,
        })
```

#### Checklist rapide

| Élément | Comment |
| ------- | ------- |
| Table class | `tables.Table` (PAS `BaseTable`) |
| `Meta.template_name` | `"django_tables2/bootstrap5.html"` |
| `Meta.attrs` | `{"class": "table table-hover nb-table-headings"}` |
| Form class | `NautobotFilterForm` avec `model = Device` |
| Template extends | `base.html` (PAS `generic/object_list.html`) |
| `{% load %}` | Séparer les loads natifs et `from library` |
| Drawer block | `{% filter_form_drawer %}` avec 4 args |
| Contexte vue | `dynamic_filter_form=None`, `filter_params=[]` |
| Pagination | `RequestConfig(request, paginate={"per_page": 50}).configure(table)` |
| Bouton filter | `data-nb-toggle="drawer" data-nb-target="#FilterForm_drawer"` |

---

### 3.9 Django — Signals

#### post_migrate : toujours spécifier sender

Un signal `post_migrate` sans `sender` s'exécute pour **chaque** app Django qui migre (40+ apps dans Nautobot). Spécifier le sender pour ne l'exécuter que pour notre app :

```python
# MAUVAIS — s'exécute 40+ fois à chaque migrate
post_migrate.connect(enable_netdb_jobs)

# BON — s'exécute une seule fois pour notre app
from django.apps import apps

post_migrate.connect(
    enable_netdb_jobs,
    sender=apps.get_app_config("nautobot_netdb_tracking"),
)
```

#### Signal receiver : gérer l'idempotence

Le handler `post_migrate` peut s'exécuter plusieurs fois. Toujours écrire des handlers idempotents :

```python
def enable_netdb_jobs(sender, **kwargs):
    """Enable jobs after migration — idempotent."""
    from nautobot.extras.models import Job

    Job.objects.filter(
        module_name__startswith="nautobot_netdb_tracking",
        enabled=False,  # Ne toucher que les jobs pas encore actifs
    ).update(enabled=True, grouping="NetDB Tracking")
```

---

### 3.10 Python — Qualité de code

#### Fonction de normalisation unique (DRY)

Ne jamais dupliquer une fonction de normalisation dans plusieurs modules. Définir **une seule source de vérité** dans le module le plus bas de la hiérarchie (typiquement `models.py`) et importer partout :

```python
# MAUVAIS — deux fonctions quasi-identiques dans deux modules
# models.py : normalize_mac_address() → UPPERCASE
# jobs/collect_mac_arp.py : normalize_mac() → lowercase

# BON — une seule fonction canonique dans models.py
# models.py
def normalize_mac_address(mac: str) -> str:
    """Normalize MAC to XX:XX:XX:XX:XX:XX."""
    ...

# jobs/collect_mac_arp.py — importer depuis models
from nautobot_netdb_tracking.models import normalize_mac_address
```

#### Imports circulaires entre modules jobs

Éviter les imports directs entre modules jobs. Extraire les fonctions partagées dans `_base.py` ou `utils.py` :

```python
# MAUVAIS — import circulaire potentiel
from nautobot_netdb_tracking.jobs.collect_topology import normalize_interface_name

# BON — fonction partagée dans _base.py
from nautobot_netdb_tracking.jobs._base import normalize_interface_name
```

#### Exception handling : jamais de bare `except Exception: pass`

```python
# MAUVAIS — exception avalée silencieusement
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    pass

# BON — log l'erreur, puis continue
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    host.logger.warning("MAC collection subtask failed", exc_info=True)
```

---

### 3.11 Nautobot Status — Pièges sémantiques

#### Ne jamais utiliser un status sémantiquement incorrect comme fallback

Les statuts par défaut pour `dcim.interface` sont : **Active, Decommissioning, Failed, Maintenance, Planned**. Aucun ne correspond à "interface opérationnellement down".

```python
# INTERDIT — "Planned" signifie "pas encore déployé", pas "oper-down"
status_inactive = interface_statuses.filter(name="Planned").first()
status_inactive_obj = interface_statuses.filter(name="Inactive").first()
if status_inactive_obj:
    status_inactive = status_inactive_obj
# Si "Inactive" n'existe pas → fallback sur "Planned" → BUG

# BON — si le status n'existe pas, ne pas changer
status_down = interface_statuses.filter(name="Down").first()
# status_down peut être None → la condition short-circuite → pas de changement
if not is_up and status_down and nb_interface.status == status_active:
    nb_interface.status = status_down
```

#### Le status "Down" existe mais pas pour les interfaces

Le status "Down" est pré-installé dans Nautobot mais uniquement pour `ipam.vrf` et `vpn.vpntunnel`. Pour l'utiliser sur les interfaces, ajouter le content type via l'API ou un signal `post_migrate`.

---

### 3.12 Docker — Déploiement à chaud du plugin

#### Séquence correcte (CRITIQUE)

`pip install --upgrade` est un **no-op** si la version n'a pas changé. Le worker Celery garde l'ancien code en mémoire même après `pip install`.

```bash
# MAUVAIS — ne réinstalle pas si même version, ancien /tmp/ stale
docker cp ./plugin container:/tmp/plugin
docker exec container pip install --upgrade /tmp/plugin
docker restart container

# BON — rm, cp fresh, force-reinstall, restart, verify
for c in nautobot nautobot-worker nautobot-scheduler; do
  docker exec $c rm -rf /tmp/nautobot_netdb_tracking
  docker cp ./nautobot_netdb_tracking $c:/tmp/nautobot_netdb_tracking
  docker exec $c pip install --force-reinstall --no-deps /tmp/nautobot_netdb_tracking
done
docker restart nautobot nautobot-worker nautobot-scheduler
```

**Pourquoi `--force-reinstall --no-deps`** :
- `--force-reinstall` : force pip à réinstaller même si la version est identique
- `--no-deps` : évite de réinstaller toutes les dépendances (beaucoup plus rapide)

---

### 3.13 FakeNOS et tests d'intégration

#### Limitation critique

Les NAPALM getters "réussissent" sur FakeNOS mais retournent des **données incohérentes** (mauvais MACs, mauvaises interfaces, VLAN 666). Le fallback Netmiko/TextFSM ne se déclenche jamais car NAPALM ne raise pas d'exception.

#### Règle absolue

**JAMAIS** modifier le code de production pour contourner les limites de FakeNOS. Corriger l'infra de test à la place.

#### TextFSM : destination_port est une liste

Le champ `destination_port` du template TextFSM Cisco IOS MAC table retourne une **liste** (`['Gi1/0/1']`), pas un string :

```python
interface = entry.get("destination_port") or entry.get("interface") or ""
if isinstance(interface, list):
    interface = interface[0] if interface else ""
```

---

### 3.14 Configuration et packaging

#### Dépendances mortes dans pyproject.toml

Supprimer toute dépendance qui n'est plus importée dans le code. Vérifier avec :

```bash
rg 'import tenacity|from tenacity' nautobot_netdb_tracking/
rg 'import macaddress|from macaddress' nautobot_netdb_tracking/
```

#### Black + Ruff : un seul formateur

Configurer Black **et** Ruff crée des conflits potentiels. Choisir un seul outil. Ruff est le standard actuel (plus rapide, inclut le formatage + linting) :

```toml
# BON — ruff uniquement
[tool.ruff]
line-length = 120
```

#### CI : ne jamais commenter le job de test

Le job de test dans `.github/workflows/ci.yml` ne doit **jamais** être commenté. Un CI sans tests est un faux sentiment de sécurité.

---

### 3.15 Checklist pré-commit (complète)

#### Linting et formatage

1. `ruff check` — zéro nouvelle erreur
2. `ruff format --check` — zéro nouveau fichier à reformater

#### Modèles et ORM

3. Pas de `.save()` — toujours `validated_save()`
4. Pas de query dans une boucle — `select_related` / `prefetch_related`
5. Tout `Cable()` a un `status=` (récupéré via `Status.objects.get_for_model(Cable)`)
6. Les `UniqueConstraint` utilisent le préfixe `%(app_label)s_%(class)s_`
7. Pas de `count()` + `delete()` séparés — utiliser la valeur de retour de `delete()`

#### Vues et API

8. Les vues custom (`View`) ont `LoginRequiredMixin` + `PermissionRequiredMixin`
9. Chaque `permission_required` correspond au modèle affiché (pas une permission générique)
10. Les ViewSets API ont tous les FK du serializer dans `select_related()`
11. Pas de serializer/code mort — supprimer tout ce qui n'est pas importé

#### Jobs et signals

12. `post_migrate.connect()` a un `sender=` pour éviter les exécutions multiples
13. Pas de dépendance inutile dans `pyproject.toml` — vérifier les imports

#### Tests

14. Les fixtures utilisent `validated_save()`, pas `.create()` ni `.save()`
15. Les tests FK filters utilisent des listes : `[str(device.pk)]`
16. Pas de `.configure(request)` sur les tables
17. Le job de test CI n'est PAS commenté

#### Nornir

18. `NornirSubTaskError.result` est un `MultiResult` (liste) — itérer pour extraire la root cause
19. Ne pas raise `RuntimeError` sur échec partiel — uniquement si `devices_success == 0`

#### Python

20. Une seule fonction de normalisation par concept (DRY) — source de vérité dans `models.py`
21. Pas d'imports circulaires entre modules jobs — partager via `_base.py` ou `utils.py`
22. Pas de bare `except Exception: pass` — toujours logger avant de continuer
23. Pas de `%` formatting dans les strings (hors `logger.*`) — utiliser f-strings

#### Status et transitions

24. Ne jamais utiliser un status sémantiquement incorrect comme fallback
25. Si un status cible n'existe pas, **skip la transition** (`None` → condition short-circuite)
26. Vérifier que le status existe pour le bon content type (`dcim.interface`, pas juste `ipam.vrf`)

#### Déploiement Docker

27. `pip install --upgrade` ne réinstalle pas si même version — utiliser `--force-reinstall --no-deps`
28. Toujours `rm -rf /tmp/old` avant `docker cp` fresh
29. Toujours vérifier le code installé avec `grep` après deploy

---

## 4. Testing Patterns

Sources: `tests/conftest.py`, `tests/factories.py`, `tests/test_models.py`, `tests/test_filters.py`, `CLAUDE.md`, `SPECS.md`

### 4.1 Framework : pytest

**Règle** : pytest comme runner. Pas de `unittest.TestCase` sauf contrainte framework. Les classes de test utilisent la convention `Test*` et ne héritent pas.

```python
# Format standard
@pytest.mark.django_db
class TestMACAddressHistory:
    """Tests for MACAddressHistory model."""

    def test_create_basic(self, device, interface):
        """Test creating a basic MAC address history entry."""
        mac = MACAddressHistory(...)
        mac.validated_save()
        assert mac.pk is not None
```

**Nommage des tests** : `test_<fonction>_<scénario>_<résultat_attendu>`.

**Markers** :
- `@pytest.mark.django_db` pour tous les tests qui touchent la DB
- `@pytest.mark.integration` pour les tests réseau (configuré dans `conftest.py`)
- `@pytest.mark.slow` pour les tests lents

### 4.2 Fixtures — Toutes celles définies dans conftest.py

Fichier : `/Users/thomas/AzQore/nautobot_netdb_tracking/tests/conftest.py`

#### Fixtures Nautobot de base

| Fixture | Dépendances | Retourne | Notes |
| ------- | ----------- | -------- | ----- |
| `location_type` | `db` | `LocationType` | "Site", nestable=True, VLAN content type ajouté |
| `location` | `db`, `location_type` | `Location` | "Test Site", status=premier status disponible |
| `manufacturer` | `db` | `Manufacturer` | "Test Manufacturer" |
| `device_type` | `db`, `manufacturer` | `DeviceType` | "Test Device Type" |
| `device_role` | `db` | `Role` | "Test Role" |
| `device` | `db`, `location`, `device_type`, `device_role` | `Device` | "test-device-01" |
| `device2` | `db`, `location`, `device_type`, `device_role` | `Device` | "test-device-02" (pour topology) |
| `interface` | `db`, `device` | `Interface` | "GigabitEthernet0/1", type="1000base-t" |
| `interface2` | `db`, `device2` | `Interface` | "GigabitEthernet0/1" sur device2 |
| `vlan` | `db`, `location` | `VLAN` | vid=100, "Test VLAN", locations.add(location) |

#### Fixtures IPAM

| Fixture | Dépendances | Retourne | Notes |
| ------- | ----------- | -------- | ----- |
| `namespace` | `db` | `Namespace` | "Test Namespace" |
| `prefix` | `db`, `namespace` | `Prefix` | "192.168.1.0/24" |
| `ip_address` | `db`, `namespace`, `prefix` | `IPAddress` | host="192.168.1.50", mask_length=24, parent=prefix, status="Active" |

#### Fixtures utilisateurs et clients

| Fixture | Dépendances | Retourne | Notes |
| ------- | ----------- | -------- | ----- |
| `admin_user` | `db` | `User` | superuser username="admin" |
| `regular_user` | `db` | `User` | non-admin username="regular" |
| `api_client` | `db`, `admin_user` | `APIClient` | DRF APIClient, force_authenticate |
| `authenticated_client` | `db`, `admin_user` | `Client` | Django Client, force_login |
| `client` | `db` | `Client` | Django Client non authentifié |
| `request_factory` | — | `RequestFactory` | Pour les tests de tables et vues |

#### Fixtures modèles NetDB

| Fixture | Dépendances | Retourne | Notes |
| ------- | ----------- | -------- | ----- |
| `mac_entry` | `db`, `device`, `interface` | `MACAddressHistory` | mac="00:11:22:33:44:55", utilise `.objects.create()` |
| `arp_entry` | `db`, `device`, `interface` | `ARPEntry` | ip="192.168.1.100", mac="00:11:22:33:44:55" |
| `topology_connection` | `db`, `device`, `interface`, `device2`, `interface2` | `TopologyConnection` | protocol=LLDP |

#### Fixtures Platform

| Fixture | Dépendances | Retourne | Notes |
| ------- | ----------- | -------- | ----- |
| `platform_cisco_ios` | `db` | `Platform` | network_driver="cisco_ios" |
| `platform_arista_eos` | `db` | `Platform` | network_driver="arista_eos" |
| `device_with_platform` | `db`, `device`, `platform_cisco_ios` | `Device` | device avec platform assigné (utilise `.save()`) |

#### Fixtures VLAN supplémentaires

| Fixture | Dépendances | Retourne | Notes |
| ------- | ----------- | -------- | ----- |
| `vlan_10` | `db`, `location` | `VLAN` | vid=10, "VLAN-10" |
| `vlan_20` | `db`, `location` | `VLAN` | vid=20, "VLAN-20" |
| `vlan_30` | `db`, `location` | `VLAN` | vid=30, "VLAN-30" |

**Note** : `pytest_configure` ajoute les markers `integration` et `slow`.

### 4.3 Factory Boy — Toutes les factories définies

Fichier : `/Users/thomas/AzQore/nautobot_netdb_tracking/tests/factories.py`

Toutes héritent de `factory.django.DjangoModelFactory`.

#### LocationTypeFactory

```python
class LocationTypeFactory(DjangoModelFactory):
    class Meta:
        model = LocationType
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Location Type {n}")
    nestable = True

    @factory.post_generation
    def setup_content_types(self, create, extracted, **kwargs):
        if create:
            vlan_ct = ContentType.objects.get_for_model(VLAN)
            self.content_types.add(vlan_ct)
```

#### LocationFactory

```python
class LocationFactory(DjangoModelFactory):
    class Meta:
        model = Location
        django_get_or_create = ("name", "location_type")

    name = factory.Sequence(lambda n: f"Location {n}")
    location_type = factory.SubFactory(LocationTypeFactory)

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Location).first()
```

#### ManufacturerFactory

```python
class ManufacturerFactory(DjangoModelFactory):
    class Meta:
        model = Manufacturer
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Manufacturer {n}")
```

#### DeviceTypeFactory

```python
class DeviceTypeFactory(DjangoModelFactory):
    class Meta:
        model = DeviceType
        django_get_or_create = ("model", "manufacturer")

    model = factory.Sequence(lambda n: f"Device Type {n}")
    manufacturer = factory.SubFactory(ManufacturerFactory)
```

#### RoleFactory

```python
class RoleFactory(DjangoModelFactory):
    class Meta:
        model = Role
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Role {n}")
```

#### DeviceFactory

```python
class DeviceFactory(DjangoModelFactory):
    class Meta:
        model = Device

    name = factory.Sequence(lambda n: f"device-{n:03d}")
    location = factory.SubFactory(LocationFactory)
    device_type = factory.SubFactory(DeviceTypeFactory)
    role = factory.SubFactory(RoleFactory)

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Device).first()
```

#### InterfaceFactory

```python
class InterfaceFactory(DjangoModelFactory):
    class Meta:
        model = Interface

    name = factory.Sequence(lambda n: f"GigabitEthernet0/{n}")
    device = factory.SubFactory(DeviceFactory)
    type = "1000base-t"

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(Interface).first()
```

#### VLANFactory

```python
class VLANFactory(DjangoModelFactory):
    class Meta:
        model = VLAN

    vid = factory.Sequence(lambda n: (n % 4094) + 1)
    name = factory.LazyAttribute(lambda o: f"VLAN{o.vid}")

    @factory.lazy_attribute
    def status(self):
        return Status.objects.get_for_model(VLAN).first()

    @factory.post_generation
    def locations(self, create, extracted, **kwargs):
        """Add locations after VLAN creation (M2M in Nautobot 3.x)."""
        if not create:
            return
        if extracted:
            for loc in extracted:
                self.locations.add(loc)
```

#### MACAddressHistoryFactory

```python
class MACAddressHistoryFactory(DjangoModelFactory):
    class Meta:
        model = MACAddressHistory

    device = factory.SubFactory(DeviceFactory)
    interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.device))
    mac_address = factory.Sequence(lambda n: f"00:11:22:33:{(n // 256):02X}:{(n % 256):02X}")
    vlan = factory.SubFactory(VLANFactory)
    last_seen = factory.LazyFunction(timezone.now)
```

**Point critique** : `interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.device))` — l'interface est créée sur le même device que celui de la factory. Cela évite la violation de la contrainte `interface.device == device`.

#### ARPEntryFactory

```python
class ARPEntryFactory(DjangoModelFactory):
    class Meta:
        model = ARPEntry

    device = factory.SubFactory(DeviceFactory)
    interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.device))
    ip_address = factory.Sequence(lambda n: f"10.0.{(n // 256) % 256}.{n % 256}")
    ip_address_object = None
    mac_address = factory.Sequence(lambda n: f"00:AA:BB:CC:{(n // 256):02X}:{(n % 256):02X}")
    last_seen = factory.LazyFunction(timezone.now)
```

#### TopologyConnectionFactory

```python
class TopologyConnectionFactory(DjangoModelFactory):
    class Meta:
        model = TopologyConnection

    local_device = factory.SubFactory(DeviceFactory)
    local_interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.local_device))
    remote_device = factory.SubFactory(DeviceFactory)
    remote_interface = factory.LazyAttribute(lambda o: InterfaceFactory(device=o.remote_device))
    protocol = TopologyConnection.Protocol.LLDP
    last_seen = factory.LazyFunction(timezone.now)
```

### 4.4 Mock patterns

**Mocking des appels réseau** (Nornir, NAPALM, Netmiko) — toujours via `unittest.mock` :

```python
from unittest.mock import MagicMock, patch

@patch("nautobot_netdb_tracking.jobs._base.InitNornir")
@patch("nautobot_netdb_tracking.jobs._base.NautobotORMInventory", None)
def test_job_commit_mode(self, mock_init_nornir, device_with_platform, interface):
    mock_nr = MagicMock()
    mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}
    mock_init_nornir.return_value = mock_nr

    mock_host_result = MagicMock()
    mock_host_result.failed = False
    mock_host_result.result = {
        "mac_table": [
            {"interface": "GigabitEthernet0/1", "mac": "AA:BB:CC:DD:EE:FF", "vlan": 100}
        ],
        "arp_table": [],
    }
    mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

    job = CollectMACARPJob()
    job.logger = MagicMock()
    result = job.run(
        device=device_with_platform,
        workers=1,
        timeout=30,
        commit=True,
        collect_mac=True,
        collect_arp=True,
    )
    assert result["success"] is True
```

**Mocking du logger** :

```python
job = MyJob()
job.logger = MagicMock()
# Ensuite vérifier les appels
job.logger.error.assert_called_once()
```

### 4.5 Comment les Jobs sont testés

**Pattern standard** :
1. Mocker `InitNornir` et `NautobotORMInventory`
2. Configurer `mock_nr.run.return_value` avec les données de résultat
3. Appeler `job.run(...)` directement
4. Vérifier les stats, les objets créés en DB, et les appels logger

**Test dry-run** :

```python
def test_dry_run_creates_no_records(self, mock_init_nornir, device_with_platform, interface):
    # ... setup mock ...
    result = job.run(..., commit=False, ...)
    assert MACAddressHistory.objects.count() == 0
```

**Test NetDB logic (UPDATE vs INSERT)** :

```python
def test_update_existing_entry(self, device, interface):
    existing = MACAddressHistory(...)
    existing.validated_save()
    first_seen_before = existing.first_seen

    entry, created = MACAddressHistory.update_or_create_entry(
        device=device, interface=interface, mac_address="00:11:22:33:44:55"
    )
    assert created is False
    assert entry.first_seen == first_seen_before  # first_seen non modifié
    assert entry.last_seen > existing.last_seen   # last_seen mis à jour
```

**Test échec total (RuntimeError)** :

```python
def test_all_devices_failed_raises_runtime_error(self, mock_init_nornir, device_with_platform):
    mock_nr = MagicMock()
    mock_nr.inventory.hosts = {device_with_platform.name: MagicMock()}
    mock_init_nornir.return_value = mock_nr

    mock_host_result = MagicMock()
    mock_host_result.failed = True
    mock_nr.run.return_value = {device_with_platform.name: mock_host_result}

    job = CollectMACARPJob()
    job.logger = MagicMock()

    with pytest.raises(RuntimeError):
        job.run(...)
    assert job.stats["devices_success"] == 0
```

### 4.6 FilterSet input format dans les tests (CRITIQUE)

**Règle absolue** : `NaturalKeyOrPKMultipleChoiceFilter` (utilisé pour les FK comme `device`, `interface`, `vlan`, `location`, `device_role`) attend un **input sous forme de liste de strings**.

```python
# MAUVAIS — bare value pour les filtres FK
filterset = MACAddressHistoryFilterSet({"device": device.pk})
filterset = MACAddressHistoryFilterSet({"device": device.name})

# BON — wrapper dans une liste de strings
filterset = MACAddressHistoryFilterSet({"device": [str(device.pk)]})
filterset = MACAddressHistoryFilterSet({"device": [device.name]})

# Exemple complet de test
@pytest.mark.django_db
def test_filter_by_device(self, device, interface):
    mac = MACAddressHistoryFactory(device=device, interface=interface)
    other_mac = MACAddressHistoryFactory()  # Autre device

    filterset = MACAddressHistoryFilterSet({"device": [str(device.pk)]})
    qs = filterset.qs

    assert mac in qs
    assert other_mac not in qs

# CharFilter — string simple (pas de liste)
filterset = MACAddressHistoryFilterSet({"mac_address": "00:11:22"})
filterset = MACAddressHistoryFilterSet({"q": "search term"})
filterset = MACAddressHistoryFilterSet({"ip_address": "192.168"})
```

---

## 5. Plugin Configuration

Sources: `nautobot_netdb_tracking/__init__.py`, `nautobot_netdb_tracking/signals.py`

### 5.1 NautobotAppConfig — Tous les attributs

Fichier : `/Users/thomas/AzQore/nautobot_netdb_tracking/nautobot_netdb_tracking/__init__.py`

```python
from importlib.metadata import metadata
from nautobot.apps import NautobotAppConfig

__version__ = metadata("nautobot-netdb-tracking")["Version"]


class NautobotNetDBTrackingConfig(NautobotAppConfig):
    name = "nautobot_netdb_tracking"          # nom Python du module
    verbose_name = "NetDB Tracking"           # nom affiché dans l'UI
    version = __version__                     # depuis importlib.metadata (dynamique)
    author = "Thomas"
    author_email = "thomas@networktocode.com"
    description = "Track MAC addresses, ARP entries, and network topology from network devices"
    base_url = "netdb-tracking"               # préfixe URL : /plugins/netdb-tracking/
    required_settings = []                    # aucun paramètre obligatoire
    min_version = "3.0.6"
    max_version = "3.99"
    default_settings = {
        "retention_days": 90,
        "purge_enabled": True,
        "nornir_workers": 50,
        "device_timeout": 30,
        "auto_create_cables": False,
        "mac_format": "colon_upper",  # colon_upper, colon_lower, dash_upper, dash_lower
    }

    def ready(self) -> None:
        """Hook called when Django app is ready."""
        super().ready()
        from nautobot_netdb_tracking.signals import register_signals
        register_signals(sender=self.__class__)
        self._fix_job_grouping()

    @staticmethod
    def _fix_job_grouping() -> None:
        """Ensure plugin jobs are grouped under 'NetDB Tracking'.

        Nautobot's register_jobs() resets grouping to the module path on startup.
        The post_migrate signal only fires when this plugin has new migrations.
        This method runs on every startup via ready() to fix the grouping.

        Uses QuerySet.update() to bypass validated_save() which would overwrite
        the grouping field.
        """
        from django.db import OperationalError, ProgrammingError
        try:
            from nautobot.extras.models import Job
            Job.objects.filter(
                module_name__startswith="nautobot_netdb_tracking.jobs"
            ).update(grouping="NetDB Tracking")
        except (OperationalError, ProgrammingError):
            # Tables may not exist yet during initial migration
            pass


config = NautobotNetDBTrackingConfig
```

**Points importants** :
- `version` est chargé dynamiquement via `importlib.metadata` (pas hardcodé)
- `_fix_job_grouping()` s'exécute à chaque démarrage via `ready()` pour contrer le reset du grouping par `register_jobs()`
- `try/except (OperationalError, ProgrammingError)` protège contre le cas où les tables n'existent pas encore (migration initiale)

### 5.2 default_settings

| Setting | Valeur par défaut | Type | Description |
| ------- | ----------------- | ---- | ----------- |
| `retention_days` | 90 | int | Durée de rétention des données en jours |
| `purge_enabled` | True | bool | Active la purge automatique |
| `nornir_workers` | 50 | int | Workers parallèles pour la collecte |
| `device_timeout` | 30 | int | Timeout par device en secondes |
| `auto_create_cables` | False | bool | Création automatique de cables |
| `mac_format` | `"colon_upper"` | str | Format d'affichage MAC (colon_upper, colon_lower, dash_upper, dash_lower) |

Lecture des settings à runtime :

```python
from django.conf import settings

plugin_settings = settings.PLUGINS_CONFIG.get("nautobot_netdb_tracking", {})
retention_days = plugin_settings.get("retention_days", 90)
```

### 5.3 required_settings

```python
required_settings = []  # Aucun paramètre obligatoire
```

### 5.4 Signals enregistrés (signals.py)

Fichier : `/Users/thomas/AzQore/nautobot_netdb_tracking/nautobot_netdb_tracking/signals.py`

#### Fonction `register_signals(sender)`

Appelée depuis `ready()` avec `sender=self.__class__` (l'AppConfig) pour scoper les signaux à ce plugin uniquement :

```python
def register_signals(sender):
    post_migrate.connect(_enable_plugin_jobs, sender=sender)
    post_migrate.connect(_ensure_interface_down_status, sender=sender)
```

#### `_enable_plugin_jobs(sender, **kwargs)`

Handler `post_migrate` qui active et groupe les jobs :

```python
def _enable_plugin_jobs(sender, **kwargs):
    from nautobot.extras.models import Job
    updated = Job.objects.filter(
        module_name__startswith="nautobot_netdb_tracking.jobs"
    ).update(enabled=True, grouping="NetDB Tracking")
    if updated:
        logger.info("NetDB Tracking: enabled %d jobs", updated)
```

#### `_ensure_interface_down_status(sender, **kwargs)`

Handler `post_migrate` qui ajoute le content type `dcim.interface` au status "Down" s'il n'y est pas déjà :

```python
def _ensure_interface_down_status(sender, **kwargs):
    interface_ct = ContentType.objects.get_for_model(Interface)
    status_down = Status.objects.filter(name="Down").first()
    if status_down is None:
        logger.warning("'Down' status not found — cannot assign to dcim.interface")
        return
    if not status_down.content_types.filter(pk=interface_ct.pk).exists():
        status_down.content_types.add(interface_ct)
        logger.info("Added 'Down' status to dcim.interface content type")
```

#### Fonctions utilitaires (non-signaux)

```python
def get_retention_days() -> int:
    """Get retention period in days from plugin settings. Default: 90."""

def is_purge_enabled() -> bool:
    """Check if automatic purge is enabled in plugin settings."""

def purge_old_records() -> dict[str, int]:
    """Purge records older than the retention period.
    Returns: {"mac_addresses": int, "arp_entries": int, "topology_connections": int}
    """

def get_stale_records_count(days: int = 7) -> dict[str, int]:
    """Get count of records not seen in the specified number of days."""
```

### 5.5 ready() method — Pattern complet

```python
def ready(self) -> None:
    """Hook called when Django app is ready.

    Called by Django after all apps are loaded. Used to:
    1. Import signal handlers (must be done here, not at module level)
    2. Fix job grouping on every startup
    """
    super().ready()
    # Always import signals here, never at module level
    from nautobot_netdb_tracking.signals import register_signals
    register_signals(sender=self.__class__)
    self._fix_job_grouping()
```

**Pourquoi importer les signals dans `ready()`** : les models ne sont pas encore disponibles au moment du chargement du module `__init__.py`. L'import dans `ready()` garantit que tous les models sont chargés avant d'établir les connexions de signaux.

---

## 6. pyproject.toml — Exact Configuration

Fichier : `/Users/thomas/AzQore/nautobot_netdb_tracking/pyproject.toml`

### 6.1 Dépendances exactes

```toml
[tool.poetry.dependencies]
python = ">=3.10,<3.14"
nautobot = "^3.0.6"
nornir = "^3.4.0"
nornir-nautobot = "^4.0.0"
nautobot-plugin-nornir = "^3.0.0"
nornir-napalm = "^0.5.0"
nornir-netmiko = "^1.0.0"
napalm = "^5.0.0"
netmiko = "^4.3.0"
```

### 6.2 Dev dependencies

```toml
[tool.poetry.group.dev.dependencies]
pytest = "^8.0.0"
pytest-cov = "^4.1.0"
pytest-django = "^4.8.0"
factory-boy = "^3.3.0"
coverage = "^7.4.0"
ruff = "^0.2.0"
pylint = "^3.0.0"
pylint-django = "^2.5.0"
pre-commit = "^3.6.0"
```

**Note** : pas de `black` — ruff seul est utilisé pour le formatage.

### 6.3 pytest configuration (ini_options)

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
addopts = "-v --tb=short"
DJANGO_SETTINGS_MODULE = "tests.test_settings"
```

### 6.4 Coverage configuration

```toml
[tool.coverage.run]
source = ["nautobot_netdb_tracking"]
branch = true
omit = [
    "*/migrations/*",
    "*/tests/*",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
fail_under = 80
```

### 6.5 Ruff configuration

```toml
[tool.ruff]
line-length = 120
target-version = "py310"
extend-exclude = ["migrations"]

[tool.ruff.lint]
select = [
    "E",     # pycodestyle errors
    "W",     # pycodestyle warnings
    "F",     # Pyflakes
    "I",     # isort
    "N",     # pep8-naming
    "D",     # pydocstring
    "UP",    # pyupgrade
    "B",     # flake8-bugbear
    "C4",    # flake8-comprehensions
    "DJ",    # flake8-django
    "SIM",   # flake8-simplify
    "RUF",   # Ruff-specific rules
]
ignore = [
    "D100",   # Missing docstring in public module
    "D104",   # Missing docstring in public package
    "D106",   # Missing docstring in public nested class
    "D203",   # 1 blank line required before class docstring
    "D213",   # Multi-line docstring summary should start at the second line
    "D401",   # First line of docstring should be in imperative mood
    "D406",   # Section name should end with a newline
    "D407",   # Missing dashed underline after section
    "D413",   # Missing blank line after last section
    "RUF012", # Mutable class attributes (Django admin/Meta classes are standard patterns)
    "SIM102", # Nested if statements (sometimes more readable)
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["D", "S101"]
"**/migrations/*" = ["D", "E501", "I"]

[tool.ruff.lint.isort]
known-first-party = ["nautobot_netdb_tracking"]
known-third-party = ["nautobot"]
```

### 6.6 Pylint configuration

```toml
[tool.pylint.master]
ignore = ["migrations", "tests"]
load-plugins = ["pylint_django"]
django-settings-module = "tests.test_settings"

[tool.pylint.messages_control]
disable = [
    "missing-module-docstring",
    "too-few-public-methods",
    "duplicate-code",
]

[tool.pylint.format]
max-line-length = 120
```

### 6.7 Build system

```toml
[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```

### 6.8 Package metadata

```toml
[tool.poetry]
name = "nautobot-netdb-tracking"
version = "1.0.0"
description = "Nautobot plugin for tracking MAC addresses, ARP entries, and network topology (NetDB)"
authors = ["Thomas <thomas@networktocode.com>"]
license = "Apache-2.0"
readme = "README.md"
keywords = ["nautobot", "nautobot-plugin", "netdb", "mac-tracking", "arp", "topology"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Environment :: Plugins",
    "Framework :: Django",
    "Intended Audience :: System Administrators",
    "License :: OSI Approved :: Apache Software License",
    "Operating System :: OS Independent",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: System :: Networking",
]
packages = [{ include = "nautobot_netdb_tracking" }]
```

---

## 7. Swarm Mode Patterns

Source: `CLAUDE.md` (section "Swarm Mode")

### 7.1 Quand utiliser le swarm

**Utiliser le swarm** :
- Refactoring multi-fichiers (models + views + tables + filters + templates)
- Ajout de tests pour plusieurs modules indépendants
- Audit/review de différentes parties du codebase
- Implémentation de features indépendantes en parallèle
- Recherche exploratoire sur plusieurs domaines simultanément

**Ne PAS utiliser le swarm** :
- Tâches séquentielles avec dépendances (migration avant tests, model avant view)
- Modification d'un seul fichier
- Tâches triviales (< 3 étapes)

### 7.2 Protocole swarm

1. **Décomposer** la tâche en sous-tâches indépendantes (pas de dépendances croisées)
2. **Créer un TaskList** pour tracker la progression globale
3. **Lancer les agents en parallèle** dans un seul message (multiple `Task` tool calls)
4. **Chaque agent** reçoit :
   - Un contexte clair (fichiers concernés, objectif précis)
   - Les conventions du projet (CLAUDE.md, patterns existants)
   - Des instructions explicites : recherche seule vs écriture de code
5. **Consolider** les résultats et vérifier la cohérence inter-agents
6. **Valider** avec `ruff check` + `ruff format --check` sur l'ensemble

### 7.3 Types d'agents disponibles

| Agent | Usage | Outils |
| ----- | ----- | ------ |
| `Explore` | Recherche rapide dans le codebase (fichiers, patterns, architecture) | Glob, Grep, Read |
| `Plan` | Conception de plan d'implémentation (architecture, trade-offs) | Glob, Grep, Read |
| `general-purpose` | Tâches complexes multi-étapes (recherche + exécution) | Tous |
| `Bash` | Commandes terminal (git, docker, npm) | Bash |
| `code-simplifier` | Simplification et refactoring de code existant | Tous |
| `nautobot-developer` | Dev Nautobot 3.x : models, views, API, jobs, filters, migrations | Read, Write, Edit, Bash, Glob, Grep |
| `nautobot-code-reviewer` | Review Nautobot 3.x : anti-patterns, deprecated APIs, security, performance | Read, Write, Edit, Bash, Glob, Grep |

### 7.4 Exemples de décomposition swarm

#### Audit codebase (4 agents en parallèle)

```
Agent 1 (Explore): Auditer models.py — champs, constraints, indexes, clean()
Agent 2 (Explore): Auditer jobs/ — error handling, Nornir patterns, stats
Agent 3 (Explore): Auditer views.py + templates/ — UI standards, pagination
Agent 4 (Explore): Auditer api/ — serializers, viewsets, permissions
```

#### Ajout de tests (3 agents en parallèle)

```
Agent 1 (general-purpose): Écrire tests pour models (validation, constraints)
Agent 2 (general-purpose): Écrire tests pour filters (FK filters, CharFilters)
Agent 3 (general-purpose): Écrire tests pour views (list, detail, permissions)
```

#### Feature multi-composants (séquentiel + parallèle)

```
Phase 1 (séquentiel):
  Agent Plan: Concevoir l'architecture (model, API, UI)

Phase 2 (parallèle, après validation du plan):
  Agent 1: Implémenter model + migration
  Agent 2: Implémenter serializer + API viewset
  Agent 3: Implémenter table + filter + template

Phase 3 (séquentiel):
  Consolidation: vérifier cohérence, ruff check, tests
```

### 7.5 Règles critiques pour les agents

- **Lire avant d'écrire** : chaque agent DOIT lire les fichiers existants avant modification
- **Pas de conflits** : deux agents ne doivent JAMAIS modifier le même fichier
- **Conventions** : chaque agent respecte les standards du CLAUDE.md (`validated_save`, type hints, etc.)
- **Autonomie** : l'agent doit pouvoir compléter sa tâche sans dépendre d'un autre agent
- **Rapport** : chaque agent retourne un résumé clair de ce qu'il a fait/trouvé

---

## Références officielles

1. **Nautobot Core** : https://docs.nautobot.com/projects/core/en/stable/
2. **Nautobot App Development** : https://docs.nautobot.com/projects/core/en/stable/development/apps/
3. **Nautobot Plugin Nornir** : https://docs.nautobot.com/projects/plugin-nornir/en/latest/
4. **Network-to-Code Cookiecutter** : https://github.com/nautobot/cookiecutter-nautobot-app
5. **Nornir** : https://nornir.readthedocs.io/
6. **NAPALM** : https://napalm.readthedocs.io/
7. **Django** : https://docs.djangoproject.com/en/5.0/
8. **Bootstrap 5** : https://getbootstrap.com/docs/5.3/
9. **Factory Boy** : https://factoryboy.readthedocs.io/
10. **pytest-django** : https://pytest-django.readthedocs.io/

---

**Dernière mise à jour** : 2026-02-18
**Basé sur** : `nautobot-netdb-tracking` v1.0.0 (commit de référence: 2026-02-12)
