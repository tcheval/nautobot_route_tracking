# Nautobot Plugin Development - Lessons Learned

Guide de survie pour le developpement de plugins Nautobot 3.x. Chaque section documente un piege rencontre en production et la solution correcte.

## Table des matieres

- [Nornir et parallelisme](#nornir-et-parallelisme)
- [NautobotORMInventory et NAPALM](#nautobotorminventory-et-napalm)
- [Nautobot 3.x - Modeles et ORM](#nautobot-3x---modeles-et-orm)
- [Nautobot 3.x - Jobs](#nautobot-3x---jobs)
- [Nautobot 3.x - API et serializers](#nautobot-3x---api-et-serializers)
- [Nautobot 3.x - Tests](#nautobot-3x---tests)
- [Django - Vues et templates](#django---vues-et-templates)
- [Vues custom avec filter sidebar et pagination](#vues-custom-avec-filter-sidebar-et-pagination)
- [Django - Signals](#django---signals)
- [Python - Qualite de code](#python---qualite-de-code)
- [Configuration et packaging](#configuration-et-packaging)
- [FakeNOS et tests d'integration](#fakenos-et-tests-dintegration)
- [Nautobot Status - Pieges semantiques](#nautobot-status---pieges-semantiques)
- [Docker - Deploiement a chaud du plugin](#docker---deploiement-a-chaud-du-plugin)

---

## Nornir et parallelisme

### Pattern golden-config (REFERENCE)

Le pattern de reference est celui de [nautobot-app-golden-config](https://github.com/nautobot/nautobot-app-golden-config/tree/v3.0.2/nautobot_golden_config/nornir_plays). Tout job Nornir doit le suivre.

**Correct** : un seul `nr.run()` sur tous les hosts en parallele.

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

### Erreurs a ne JAMAIS faire

| Anti-pattern | Pourquoi c'est mauvais |
| ------------ | ---------------------- |
| Boucle serielle de reachability check AVANT `nr.run()` | Defeat le parallelisme. Un check TCP par device = N * 5s en serie |
| `nr.filter(name=device_name).run()` dans une boucle | Idem — execution sequentielle deguisee |
| Retry logic apres `nr.run()` avec `time.sleep()` | Bloque tout le job. Nornir gere les timeouts nativement |
| `tenacity` retry decorator sur `_collect_from_host()` | Complexite inutile. Si un device fail, il fail — on log et on continue |
| `_collect_from_host()` per-device method | Dead code quand on utilise `_combined_*_task` avec `nr.run()` |

### Task combinee (pattern correct)

Pour collecter plusieurs types de donnees sur un meme host dans une seule session SSH :

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

### NornirSubTaskError : extraction de la root cause (CRITIQUE)

Quand `task.run()` echoue (SSH timeout, connection refused, auth failure), Nornir raise `NornirSubTaskError`. L'attribut `exc.result` est un **`MultiResult`** (liste de `Result`), PAS un `Result` unique. Acceder a `exc.result.exception` ne fonctionne jamais car les listes n'ont pas d'attribut `.exception`.

```python
# MAUVAIS — exc.result est une liste, .exception n'existe pas
# Fallback sur str(exc) = "Subtask: collect_mac_table_task (failed)"
except NornirSubTaskError as exc:
    root_cause = (
        exc.result.exception
        if hasattr(exc.result, "exception") and exc.result.exception
        else exc  # ← toujours ce branch, message generique inutile
    )

# BON — iterer le MultiResult pour trouver le Result failed
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

**Avant** (message inutile) :

```
[error] [arista-sw01] Collection failed: MAC: Subtask: collect_mac_table_task (failed)
```

**Apres** (root cause visible) :

```
[error] [arista-sw01] Collection failed: MAC: MAC collection failed (NAPALM + TextFSM):
  TCP connection to device failed.
  Common causes: 1. Incorrect hostname or IP address. 2. Wrong TCP port.
  Device settings: arista_eos 172.28.0.11:22
```

### Job partiel : ne pas raise RuntimeError sur devices_failed > 0

Un job de collecte sur 1500 devices aura inevitablement quelques echecs (maintenance, panne, ACL). Marquer le job entier comme FAILURE empeche le monitoring de distinguer un vrai probleme d'un fonctionnement normal.

```python
# MAUVAIS — 3 devices down sur 1500 = job FAILURE + RuntimeError dans Celery
if self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

# BON — FAILURE uniquement si AUCUN device n'a reussi (panne infra globale)
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(summary_msg)

return {
    "success": self.stats["devices_failed"] == 0,  # True si 100% success
    "summary": summary_msg,
    **self.stats,
}
```

| Scenario | Avant | Apres |
| -------- | ----- | ----- |
| 1500/1500 OK | SUCCESS | SUCCESS |
| 1497/1500 OK, 3 down | FAILURE + RuntimeError | SUCCESS (success=False dans result) |
| 0/1500 OK (panne infra) | FAILURE + RuntimeError | FAILURE + RuntimeError |

### Mocking Nornir dans les tests

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

## NautobotORMInventory et NAPALM

### Probleme : network_driver != napalm_driver

`NautobotORMInventory` utilise `Platform.network_driver` (ex: `arista_eos`) pour `host.platform`. Mais NAPALM attend `Platform.napalm_driver` (ex: `eos`). Sans correction, NAPALM echoue a trouver le bon driver.

### Probleme : les extras host-level ecrasent les defaults

Les extras configures par host dans `NautobotORMInventory` (via config context) **remplacent** les defaults passes a InitNornir, au lieu de les merger. On perd donc `transport`, `timeout`, etc.

### Solution : injection post-init

Apres `InitNornir()`, boucler sur les hosts pour :

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

### Config context pour le port SSH

Le port SSH custom (ex: FakeNOS sur 6001-6005) doit etre dans le config context du device, sous la cle `nautobot_plugin_nornir.connection_options` :

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

Necessite `use_config_context.connection_options: True` dans `PLUGINS_CONFIG["nautobot_plugin_nornir"]`.

---

## Nautobot 3.x - Modeles et ORM

### IPAddress : champs renommes depuis Nautobot 2.x

| Nautobot 2.x | Nautobot 3.x | Notes |
| ------------ | ------------ | ----- |
| `address="10.0.0.1/24"` | `host="10.0.0.1"` + `mask_length=24` | Separe en deux champs |
| `namespace=ns` | `parent=prefix` | Le namespace est porte par le Prefix |

### Job.grouping ecrase par validated_save()

Le champ `grouping` d'un Job est ecrase par `validated_save()`. Utiliser `QuerySet.update()` :

```python
Job.objects.filter(module_name__startswith="nautobot_netdb_tracking").update(
    enabled=True, grouping="NetDB Tracking"
)
```

### validated_save() TOUJOURS

Jamais `.save()` ni `objects.create()`. Toujours `instance.validated_save()` ou le pattern `update_or_create_entry` custom.

### select_related / prefetch_related

Jamais de queryset dans une boucle. Pre-fetch :

```python
# MAUVAIS — N+1 queries
for mac in MACAddressHistory.objects.all():
    print(mac.device.name)

# BON — 1 query
for mac in MACAddressHistory.objects.select_related("device", "interface"):
    print(mac.device.name)
```

### Cable : Status obligatoire en Nautobot 3.x

En Nautobot 3.x, le modele Cable **exige** un Status. Sans ca, `validated_save()` leve une `ValidationError`. Toujours recuperer le Status "Connected" avant de creer un Cable :

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

### UniqueConstraint : convention de nommage

Les noms de `UniqueConstraint` doivent utiliser le prefixe `%(app_label)s_%(class)s_` pour eviter les collisions entre plugins :

```python
# MAUVAIS — risque de collision avec d'autres plugins
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["device", "interface", "mac_address", "vlan"],
            name="unique_mac_entry"
        )
    ]

# BON — prefixe unique par app/model
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["device", "interface", "mac_address", "vlan"],
            name="%(app_label)s_%(class)s_unique_mac_entry"
        )
    ]
```

### natural_key_field_lookups pour les modeles

Les modeles Nautobot 3.x doivent definir `natural_key_field_lookups` dans leur Meta pour le support des natural keys dans l'API et les filtres. Sans ca, les lookups par natural key echouent silencieusement :

```python
class MACAddressHistory(PrimaryModel):
    class Meta:
        natural_key_field_lookups = {
            "device__name": "device",
            "interface__name": "interface",
            "mac_address": "mac_address",
        }
```

### Race condition : count() puis delete()

Le pattern `count()` suivi de `delete()` est non-atomique. Un autre processus peut modifier les donnees entre les deux appels. Utiliser la valeur de retour de `delete()` :

```python
# MAUVAIS — race condition, le count peut ne pas correspondre au delete
count = queryset.filter(last_seen__lt=cutoff).count()
queryset.filter(last_seen__lt=cutoff).delete()
stats["deleted"] = count

# BON — atomique, pas de fenetre de race
deleted_count, _ = queryset.filter(last_seen__lt=cutoff).delete()
stats["deleted"] = deleted_count
```

---

## Nautobot 3.x - Jobs

### Enregistrement des jobs (OBLIGATOIRE)

`jobs/__init__.py` DOIT appeler `register_jobs()`. Sans ca, les jobs sont importables mais n'apparaissent pas dans l'UI :

```python
from nautobot.core.celery import register_jobs
from myapp.jobs.my_job import MyJob

jobs = [MyJob]
register_jobs(*jobs)
```

### ScriptVariable : acces aux attributs

Les defaults et contraintes sont dans `field_attrs`, pas en attributs directs :

```python
# MAUVAIS
job.retention_days.default  # AttributeError
job.retention_days.min_value  # AttributeError

# BON
job.retention_days.field_attrs["initial"]  # 90
job.retention_days.field_attrs["min_value"]  # 1
```

### Plugin registration en test

`test_settings.py` a besoin des DEUX :

```python
PLUGINS = ["nautobot_netdb_tracking"]           # pour nautobot-server (CI)
INSTALLED_APPS.append("nautobot_netdb_tracking")  # pour pytest-django
```

`django.setup()` ne traite PAS `PLUGINS`. `nautobot-server` ne lit PAS `DJANGO_SETTINGS_MODULE`.

### CI : migrations

Utiliser `nautobot-server init` puis ajouter le plugin, pas `django-admin` :

```yaml
- name: Initialize Nautobot configuration
  run: |
    poetry run nautobot-server init
    echo 'PLUGINS = ["nautobot_netdb_tracking"]' >> ~/.nautobot/nautobot_config.py
- name: Run migrations
  run: poetry run nautobot-server makemigrations nautobot_netdb_tracking
```

---

## Nautobot 3.x - API et serializers

### select_related dans les ViewSets API

Les `NautobotModelViewSet` doivent inclure **tous** les champs FK utilises par le serializer dans `select_related()`. Sinon, chaque objet serialise genere des requetes supplementaires (N+1) :

```python
# MAUVAIS — ip_address_object est dans le serializer mais pas dans select_related
class ARPEntryViewSet(NautobotModelViewSet):
    queryset = ARPEntry.objects.select_related(
        "device", "device__location", "interface",
    ).prefetch_related("tags")

# BON — tous les FK du serializer sont pre-charges
class ARPEntryViewSet(NautobotModelViewSet):
    queryset = ARPEntry.objects.select_related(
        "device", "device__location", "interface", "ip_address_object",
    ).prefetch_related("tags")
```

**Regle** : pour chaque champ FK dans le `fields` du serializer, verifier qu'il est dans `select_related()` du ViewSet correspondant (UI et API).

### Nested serializers : ne pas creer de code mort

Ne pas declarer de serializers "nested" ou "lite" par anticipation. Un serializer non-importe nulle part est du code mort qui cree de la confusion et de la dette technique :

```python
# MAUVAIS — serializer declare mais jamais utilise
class MACAddressHistoryNestedSerializer(NautobotModelSerializer):
    class Meta:
        model = MACAddressHistory
        fields = ["id", "url", "display", "mac_address", "last_seen"]

# BON — ne creer que ce qui est effectivement utilise
# Si un nested serializer devient necessaire, le creer a ce moment-la
```

---

## Nautobot 3.x - Tests

### FilterSet : format des inputs

| Type de filtre | Format attendu | Exemple |
| -------------- | -------------- | ------- |
| `NaturalKeyOrPKMultipleChoiceFilter` (FK) | Liste de strings | `{"device": [str(device.pk)]}` |
| `CharFilter` | String simple | `{"mac_address": "00:11:22"}` |

### NaturalKeyOrPKMultipleChoiceFilter : to_field_name

`NaturalKeyOrPKMultipleChoiceFilter` utilise `to_field_name="name"` par defaut pour le lookup par natural key. Mais certains modeles Nautobot n'ont pas de champ `name` — par exemple `IPAddress` qui utilise `host` :

```python
# MAUVAIS — FieldError: Cannot resolve keyword 'name' into field
ip_address_object = NaturalKeyOrPKMultipleChoiceFilter(
    queryset=IPAddress.objects.all(),
    label="IPAM IP Address",
)

# BON — specifier le bon champ de lookup
ip_address_object = NaturalKeyOrPKMultipleChoiceFilter(
    queryset=IPAddress.objects.all(),
    to_field_name="host",
    label="IPAM IP Address",
)
```

**Regle** : toujours verifier que le modele cible a un champ `name`. Sinon, specifier `to_field_name` explicitement.

### BaseTable : pas de configure()

Nautobot `BaseTable` n'a PAS de methode `configure(request)`. Ne jamais l'appeler :

```python
# MAUVAIS — AttributeError
table = MACAddressHistoryTable(data)
table.configure(request)

# BON
table = MACAddressHistoryTable(data)
```

Les cellules null FK peuvent render en `&mdash;` (HTML entity), pas juste `—` ou `""`.

### Tab view templates : render_table et obj_table.html

`{% render_table table %}` sans argument template utilise le `DJANGO_TABLES2_TEMPLATE` de Nautobot (`utilities/obj_table.html`). Ce template accede a `table.context` qui n'existe que si la table a ete configuree via `RequestConfig`. Les tab views (Device/Interface tabs) creent des tables sans `RequestConfig` → crash `AttributeError: object has no attribute 'context'`.

```django
{# MAUVAIS — crash sur les tab views #}
{% render_table table %}

{# BON — force un template simple qui ne requiert pas table.context #}
{% render_table table "django_tables2/bootstrap5.html" %}
```

### test_settings.py : CACHES doit inclure TIMEOUT

La config `CACHES` dans `test_settings.py` doit inclure `"TIMEOUT"` sinon `KeyError: 'TIMEOUT'` :

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

### Nautobot 3.x export : ExportTemplate obligatoire

Nautobot 3.x utilise des objets `ExportTemplate` pour l'export CSV/YAML. Sans `ExportTemplate` configuree, une requete `?export=csv` retourne **404** (pas un CSV vide ni une erreur 500). Les tests doivent en tenir compte :

```python
# BON — tester que l'export sans template renvoie 404
def test_export_without_template(self, authenticated_client):
    url = reverse("plugins:myapp:mymodel_list")
    response = authenticated_client.get(url, {"export": "csv"})
    assert response.status_code == 404
```

### API test URLs : reverse() vs hardcoded paths

`reverse()` avec des namespaces imbriques (`plugins-api:myapp-api:mymodel-list`) est fragile dans les environnements de test ou les URLs du plugin sont injectees dans les resolvers de Nautobot. Le cache de `URLResolver.namespace_dict` n'est pas toujours correctement invalide.

**Solution fiable** : utiliser des chemins URL hardcodes dans les tests API :

```python
# MAUVAIS — NoReverseMatch si le namespace n'est pas correctement injecte
url = reverse("plugins-api:nautobot_netdb_tracking-api:macaddresshistory-list")

# BON — fiable, pas de dependance au resolver
_API_BASE = "/api/plugins/netdb-tracking"

def _mac_list_url():
    return f"{_API_BASE}/mac-address-history/"

def _mac_detail_url(pk):
    return f"{_API_BASE}/mac-address-history/{pk}/"
```

### Mocking des jobs Nornir

Voir la section [Mocking Nornir dans les tests](#mocking-nornir-dans-les-tests).

Le job ne raise `RuntimeError` que si **tous** les devices echouent (`devices_success == 0`). Pour les echecs partiels, le job retourne normalement avec `success=False` :

```python
# Test echec partiel — le job retourne normalement
result = job.run(...)
assert result["success"] is False
assert job.stats["devices_failed"] == 1
assert job.stats["devices_success"] > 0

# Test echec total — le job raise RuntimeError
with pytest.raises(RuntimeError):
    job.run(...)  # tous les devices echouent
assert job.stats["devices_success"] == 0
```

### conftest.py : utiliser validated_save()

Les fixtures de test doivent utiliser `validated_save()`, pas `.create()` ni `.save()`. Cela garantit que les memes validations appliquees en production sont exercees dans les tests :

```python
# MAUVAIS — contourne les validations du modele
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

### Couverture de tests : zones souvent oubliees

Les categories suivantes sont frequemment oubliees et causent des regressions en production :

| Zone a tester | Pourquoi |
| ------------- | -------- |
| Forms (`NautobotModelForm`, `NautobotFilterForm`) | Valider les `query_params`, `required`, widgets, et la methode `clean()` |
| TemplateExtension (`template_content.py`) | Verifier le rendu HTML, les contextes, et les requetes N+1 dans les panels |
| Permissions sur les vues custom | Verifier que les vues non-NautobotUIViewSet renvoient 403/302 pour les anonymes |
| CI test job actif | Le job de test dans `.github/workflows/ci.yml` ne doit jamais etre commente |

### Tests de permissions sur les vues

Toujours tester qu'un utilisateur non-authentifie est redirige (302) ou rejete (403) :

```python
def test_dashboard_requires_login(client):
    """Verify anonymous users are redirected to login."""
    response = client.get("/plugins/netdb-tracking/dashboard/")
    assert response.status_code == 302
    assert "/login/" in response.url

def test_dashboard_requires_permission(authenticated_client):
    """Verify permission check is enforced."""
    # User without 'view_macaddresshistory' permission
    response = authenticated_client.get("/plugins/netdb-tracking/dashboard/")
    assert response.status_code == 403
```

---

## Django - Vues et templates

### Mixins d'authentification

Les vues custom (non-NautobotUIViewSet) DOIVENT avoir les mixins auth :

```python
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin

class NetDBDashboardView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_macaddresshistory"
```

`NautobotUIViewSet` gere l'auth automatiquement. Les `View` Django standard ne le font PAS.

**Attention aux tab views** : les vues utilisees comme tabs sur les pages Device/Interface via `TemplateExtension` sont des `View` Django standard. Elles sont appelees en AJAX depuis la page detail, mais restent des endpoints HTTP accessibles directement. Sans auth, n'importe quel utilisateur peut acceder aux donnees via l'URL directe :

```python
# MAUVAIS — accessible sans authentification
class DeviceMACTabView(View):
    def get(self, request, pk):
        ...

# BON — auth + permissions model-specific
class DeviceMACTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_macaddresshistory"

    def get(self, request, pk):
        ...

class DeviceARPTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_arpentry"

class DeviceTopologyTabView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "nautobot_netdb_tracking.view_topologyconnection"
```

**Regle** : chaque `permission_required` doit correspondre au modele affiche par la vue, pas une permission generique commune a toutes les vues.

### QueryDict.pop() vs getlist()

`QueryDict.pop(key)` retourne la **derniere valeur** (un string unique), pas une liste. Pour les parametres multi-valeur (ex: `?device=uuid1&device=uuid2`), utiliser `request.GET.getlist()` :

```python
# MAUVAIS — retourne "uuid2" (string), pas ["uuid1", "uuid2"]
devices = request.GET.pop("device", None)

# BON — retourne ["uuid1", "uuid2"]
devices = request.GET.getlist("device")
```

### Template tags

Les filtres Django externes necessitent un `{% load %}` explicite :

```django
{# MAUVAIS — TemplateSyntaxError #}
{% load helpers %}
{{ value|intcomma }}

{# BON #}
{% load helpers humanize %}
{{ value|intcomma }}
```

### Optimisation des queries dans les vues

Utiliser les aggregations DB plutot que les boucles Python :

```python
# MAUVAIS — 3 * N queries (N = nombre de jours)
for day_offset in range(30):
    mac_count = MACAddressHistory.objects.filter(
        first_seen__gte=start, first_seen__lte=end
    ).count()

# BON — 3 queries total
from django.db.models.functions import TruncDate
mac_counts = dict(
    MACAddressHistory.objects.filter(first_seen__gte=start_date)
    .annotate(date=TruncDate("first_seen"))
    .values("date")
    .annotate(count=Count("id"))
    .values_list("date", "count")
)
```

---

## Vues custom avec filter sidebar et pagination

Quand on cree une page custom (pas un `NautobotUIViewSet`) mais qu'on veut le look natif Nautobot — filter sidebar coulissante, pagination, boutons — il y a 5 pieges majeurs. Cette section documente le pattern complet.

### Piege 1 : `generic/object_list.html` est couple a NautobotUIViewSet

**NE PAS** etendre `generic/object_list.html` pour une vue custom. Ce template est fortement couple au contexte fourni par `NautobotHTMLRenderer` :

- `content_type.model_class` — utilise pour `plugin_buttons`, `add_button`, `export_button`, bulk actions
- `model.is_saved_view_model` — controle la section saved views
- `table.configurable_columns` — methode de `BaseTable`, absente sur `tables.Table`

**Solution** : etendre `base.html` et ajouter manuellement le drawer + table + pagination.

### Piege 2 : `BaseTable` requiert un `Meta.model`

`BaseTable.__init__` appelle `CustomField.objects.get_for_model(model)`. Si `Meta.model` est `None` (table basee sur des dicts, pas un QuerySet), ca crash avec `AttributeError: 'NoneType' object has no attribute '_meta'`.

**Solution** : utiliser `django_tables2.Table` au lieu de `BaseTable` :

```python
import django_tables2 as tables

class MyCustomTable(tables.Table):  # PAS BaseTable !
    col1 = tables.Column()
    col2 = tables.TemplateColumn(template_code="...")

    class Meta:
        template_name = "django_tables2/bootstrap5.html"  # OBLIGATOIRE (voir piege 3)
        attrs = {"class": "table table-hover nb-table-headings"}
        fields = ("col1", "col2")
```

### Piege 3 : le template django-tables2 par defaut est un template Nautobot custom

`DJANGO_TABLES2_TEMPLATE` est configure sur `utilities/obj_table.html` dans Nautobot. Ce template accede a `table.data.verbose_name_plural`, `permissions.change`, `bulk_edit_url`, etc. — tout ca est absent pour une `tables.Table` avec des dicts.

**Solution** : forcer `template_name = "django_tables2/bootstrap5.html"` dans `Meta`.

### Piege 4 : `{% filter_form_drawer %}` a 4 args positionnels obligatoires

```django
{# MAUVAIS — TemplateSyntaxError: did not receive value(s) for 'filter_params' #}
{% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title %}

{# BON #}
{% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title filter_params=filter_params %}
```

La vue DOIT passer `dynamic_filter_form` (= `None`) et `filter_params` (= `[]`) dans le contexte.

### Piege 5 : `{% load X Y Z from library %}` charge X, Y, Z depuis library

```django
{# MAUVAIS — Django cherche "helpers" et "humanize" dans django_tables2 #}
{% load helpers humanize render_table from django_tables2 %}

{# BON — load separement #}
{% load helpers humanize %}
{% load render_table from django_tables2 %}
```

### Pattern complet — Vue

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

        # ... build data (list of dicts) ...
        all_data = [{"col1": "a", "col2": "b"}, ...]

        # Paginated table
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

### Pattern complet — Form (NautobotFilterForm)

```python
from django import forms
from nautobot.apps.forms import DynamicModelMultipleChoiceField, NautobotFilterForm
from nautobot.dcim.models import Device

class MyFilterForm(NautobotFilterForm):
    model = Device  # requis par les mixins NautobotFilterForm
    q = forms.CharField(required=False, label="Search")
    device = DynamicModelMultipleChoiceField(queryset=Device.objects.all(), required=False)
    # ... autres champs ...
```

### Pattern complet — Table (django_tables2.Table)

```python
import django_tables2 as tables

class MyCustomTable(tables.Table):
    col1 = tables.Column(verbose_name="Column 1")
    col2 = tables.TemplateColumn(
        template_code='{% if value %}<span class="badge bg-success">{{ value }}</span>{% endif %}',
        verbose_name="Column 2",
    )

    class Meta:
        template_name = "django_tables2/bootstrap5.html"
        attrs = {"class": "table table-hover nb-table-headings"}
        fields = ("col1", "col2")
```

### Pattern complet — Template

```django
{% extends "base.html" %}
{% load helpers humanize %}
{% load render_table from django_tables2 %}

{% block title %}My Page{% endblock %}

{% block breadcrumbs %}
<li class="breadcrumb-item"><a href="...">Parent</a></li>
<li class="breadcrumb-item active">My Page</li>
{% endblock %}

{% block drawer %}
    {% filter_form_drawer filter_form dynamic_filter_form model_plural_name=title filter_params=filter_params %}
{% endblock drawer %}

{% block content %}
<!-- Optional stats bar / header -->
<div class="row mb-4">...</div>

<!-- Filter + action buttons -->
<div class="d-flex justify-content-between align-items-center mb-3">
    <div>
        <button type="button" class="btn btn-sm btn-ghost-dark"
                data-nb-toggle="drawer" data-nb-target="#FilterForm_drawer">
            <i class="mdi mdi-filter"></i> Filters
        </button>
    </div>
    <div>
        <!-- Export, other action buttons -->
    </div>
</div>

<!-- Table with pagination -->
<div class="card">
    <div class="card-body p-0">
        {% render_table table %}
    </div>
</div>
{% endblock %}
```

### Checklist rapide

| Element | Comment |
| --- | --- |
| Table class | `tables.Table` (PAS `BaseTable`) |
| `Meta.template_name` | `"django_tables2/bootstrap5.html"` |
| `Meta.attrs` | `{"class": "table table-hover nb-table-headings"}` |
| Form class | `NautobotFilterForm` avec `model = Device` |
| Template extends | `base.html` (PAS `generic/object_list.html`) |
| `{% load %}` | Separer les loads natifs et `from library` |
| Drawer block | `{% filter_form_drawer %}` avec 4 args |
| Contexte vue | `dynamic_filter_form=None`, `filter_params=[]` |
| Pagination | `RequestConfig(request, paginate={"per_page": 50}).configure(table)` |
| Bouton filter | `data-nb-toggle="drawer" data-nb-target="#FilterForm_drawer"` |

### Reference : implementation existante

Voir `SwitchReportView` dans `views.py`, `SwitchReportTable` dans `tables.py`, `SwitchReportFilterForm` dans `forms.py`, et `switch_report.html`.

---

## Django - Signals

### post_migrate : toujours specifier sender

Un signal `post_migrate` sans `sender` s'execute pour **chaque** app Django qui migre (40+ apps dans Nautobot). Specifier le sender pour ne l'executer que pour notre app :

```python
# MAUVAIS — s'execute 40+ fois a chaque migrate
post_migrate.connect(enable_netdb_jobs)

# BON — s'execute une seule fois pour notre app
from django.apps import apps

post_migrate.connect(
    enable_netdb_jobs,
    sender=apps.get_app_config("nautobot_netdb_tracking"),
)
```

### Signal receiver : gerer l'idempotence

Le handler `post_migrate` peut s'executer plusieurs fois (redemarrage, migrations multiples). Toujours ecrire des handlers idempotents :

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

## Python - Qualite de code

### Fonction de normalisation unique (DRY)

Ne jamais dupliquer une fonction de normalisation (MAC, interface, etc.) dans plusieurs modules. Definir **une seule source de verite** dans le module le plus bas de la hierarchie (typiquement `models.py`) et importer partout :

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

Si le wrapper doit adapter l'exception (ex: `ValidationError` → `ValueError`), creer un thin wrapper qui delegue :

```python
def normalize_mac(mac: str) -> str:
    """Backward-compatible wrapper."""
    try:
        return normalize_mac_address(mac)
    except ValidationError as exc:
        raise ValueError(str(exc.message)) from exc
```

### Imports circulaires entre modules jobs

Eviter les imports directs entre modules jobs (`collect_mac_arp.py` → `collect_topology.py`). Si une fonction est partagee, l'extraire dans le module de base (`_base.py`) ou dans un module utilitaire (`utils.py`) :

```python
# MAUVAIS — import circulaire potentiel
# collect_mac_arp.py
from nautobot_netdb_tracking.jobs.collect_topology import normalize_interface_name

# BON — fonction partagee dans _base.py ou utils.py
# jobs/_base.py ou jobs/utils.py
def normalize_interface_name(interface: str) -> str:
    ...

# collect_mac_arp.py
from nautobot_netdb_tracking.jobs._base import normalize_interface_name

# collect_topology.py
from nautobot_netdb_tracking.jobs._base import normalize_interface_name
```

### Exception handling : jamais de bare `except Exception`

Ne jamais avaler silencieusement les exceptions. Toujours logger avant de `continue` ou `pass` :

```python
# MAUVAIS — exception avalee silencieusement
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    pass  # On ne saura jamais pourquoi ca a echoue

# BON — log l'erreur, puis continue
try:
    mac_sub = task.run(task=collect_mac_table_task)
except Exception:
    host.logger.warning("MAC collection subtask failed", exc_info=True)
```

### % formatting : utiliser f-strings ou .format()

Ruff UP031 signale l'utilisation de `%` pour le formatage de strings (hors `logger.*`). Utiliser des f-strings :

```python
# MAUVAIS — UP031
summary = "Job completed in %.1fs. Devices: %d success" % (elapsed, count)

# BON
summary = f"Job completed in {elapsed:.1f}s. Devices: {count} success"
```

**Exception** : les appels `logger.info("...", arg1, arg2)` doivent garder le lazy formatting `%s`/`%d` (c'est le pattern standard Python logging qui evite le formatage si le log level est desactive).

---

## Configuration et packaging

### Dependances mortes dans pyproject.toml

Supprimer toute dependance qui n'est plus importee dans le code. Les dependances inutiles :

- Augmentent le temps d'installation
- Creent des faux positifs dans les audits de securite (CVE sur un package non utilise)
- Confusent les contributeurs sur la stack technique

Verifier avec :

```bash
# Lister toutes les dependances declarees
grep -E '^\w+ = ' pyproject.toml | awk -F' ' '{print $1}'

# Verifier si chaque package est importe quelque part
rg 'import tenacity|from tenacity' nautobot_netdb_tracking/
rg 'import macaddress|from macaddress' nautobot_netdb_tracking/
```

### Black + Ruff : un seul formateur

Configurer Black **et** Ruff comme formateurs cree des conflits potentiels et de la confusion. Choisir un seul outil. Ruff est le standard actuel (plus rapide, inclut le formatage + linting) :

```toml
# MAUVAIS — deux formateurs configures dans pyproject.toml
[tool.black]
line-length = 120

[tool.ruff]
line-length = 120

# BON — ruff uniquement
[tool.ruff]
line-length = 120
```

Si Black est conserve pour compatibilite, s'assurer que les deux configs sont strictement identiques (`line-length`, `target-version`).

### URLs dans pyproject.toml

Les `homepage`, `repository`, et `documentation` dans pyproject.toml doivent pointer vers des URLs qui existent. Des URLs invalides cassent les liens sur PyPI et confusent les utilisateurs :

```toml
# MAUVAIS — URLs qui n'existent pas
homepage = "https://github.com/networktocode/nautobot-netdb-tracking"
documentation = "https://docs.nautobot.com/projects/netdb-tracking/"

# BON — URLs reelles ou les omettre
homepage = "https://github.com/tcheval/nautobot-netdb-tracking"
repository = "https://github.com/tcheval/nautobot-netdb-tracking"
```

### CI : ne jamais commenter le job de test

Le job de test dans `.github/workflows/ci.yml` ne doit **jamais** etre commente. Un CI sans tests est un faux sentiment de securite. Si les tests echouent, les corriger — ne pas desactiver le job.

---

## FakeNOS et tests d'integration

### Limitation critique

Les NAPALM getters "reussissent" sur FakeNOS mais retournent des **donnees incoherentes** (mauvais MACs, mauvaises interfaces, VLAN 666). Le fallback Netmiko/TextFSM ne se declenche jamais car NAPALM ne raise pas d'exception.

### Regle absolue

**JAMAIS** modifier le code de production pour contourner les limites de FakeNOS. Corriger l'infra de test a la place :

- Configurer les reponses FakeNOS pour retourner des donnees realistes
- Mocker les getters NAPALM dans les tests unitaires
- Reserver FakeNOS aux tests de connectivite, pas de parsing

### TextFSM : destination_port est une liste

Le champ `destination_port` du template TextFSM Cisco IOS MAC table retourne une **liste** (`['Gi1/0/1']`), pas un string. Le code gere ca correctement :

```python
interface = entry.get("destination_port") or entry.get("interface") or ""
if isinstance(interface, list):
    interface = interface[0] if interface else ""
```

### FakeNOS et get_interfaces

`get_interfaces` fonctionne sur FakeNOS (retourne des donnees), contrairement aux autres getters MAC/ARP. Mais les noms d'interfaces retournes peuvent ne pas correspondre a ceux dans Nautobot (ex: paris-rtr — 16 interfaces collectees, 0 matchees).

---

## Nautobot Status - Pieges semantiques

### Ne jamais utiliser un status semantiquement incorrect comme fallback

Les statuts par defaut pour `dcim.interface` sont : **Active, Decommissioning, Failed, Maintenance, Planned**. Aucun ne correspond a "interface operationnellement down".

```python
# ❌ DON'T — "Planned" signifie "pas encore deploye", pas "oper-down"
status_inactive = interface_statuses.filter(name="Planned").first()
status_inactive_obj = interface_statuses.filter(name="Inactive").first()
if status_inactive_obj:
    status_inactive = status_inactive_obj
# Si "Inactive" n'existe pas → fallback sur "Planned" → BUG

# ✅ DO — si le status n'existe pas, ne pas changer
status_down = interface_statuses.filter(name="Down").first()
# status_down peut etre None → la condition short-circuite → pas de changement
if not is_up and status_down and nb_interface.status == status_active:
    nb_interface.status = status_down
```

### Le status "Down" existe mais pas pour les interfaces

Le status "Down" est pre-installe dans Nautobot mais uniquement pour `ipam.vrf` et `vpn.vpntunnel`. Pour l'utiliser sur les interfaces :

```bash
# Ajouter dcim.interface au content type du status "Down"
curl -X PATCH -H 'Authorization: Token ...' -H 'Content-Type: application/json' \
  -d '{"content_types":["ipam.vrf","vpn.vpntunnel","dcim.interface"]}' \
  'http://localhost:8080/api/extras/statuses/<down-status-uuid>/'
```

---

## Docker - Deploiement a chaud du plugin

### Sequence correcte (CRITIQUE)

`pip install --upgrade` est un **no-op** si la version n'a pas change. Le worker Celery garde l'ancien code en memoire meme apres `pip install`.

```bash
# ❌ DON'T — ne reinstalle pas si meme version, ancien /tmp/ stale
docker cp ./plugin container:/tmp/plugin
docker exec container pip install --upgrade /tmp/plugin
docker restart container

# ✅ DO — rm, cp fresh, force-reinstall, restart, verify
for c in nautobot nautobot-worker nautobot-scheduler; do
  docker exec $c rm -rf /tmp/nautobot_netdb_tracking
  docker cp ./nautobot_netdb_tracking $c:/tmp/nautobot_netdb_tracking
  docker exec $c pip install --force-reinstall --no-deps /tmp/nautobot_netdb_tracking
done
docker restart nautobot nautobot-worker nautobot-scheduler

# Verifier que le code installe est le bon
docker exec nautobot-worker grep "status_down" \
  /usr/local/lib/python3.12/site-packages/nautobot_netdb_tracking/jobs/collect_mac_arp.py
```

### Pourquoi `--force-reinstall --no-deps`

- `--force-reinstall` : force pip a reinstaller meme si la version est identique
- `--no-deps` : evite de reinstaller toutes les dependances (beaucoup plus rapide)
- Sans ces flags, pip compare le numero de version et skip l'installation

---

## Checklist pre-commit

### Linting et formatage

1. `ruff check` — zero nouvelle erreur
2. `ruff format --check` — zero nouveau fichier a reformater

### Modeles et ORM

3. Pas de `.save()` — toujours `validated_save()`
4. Pas de query dans une boucle — `select_related` / `prefetch_related`
5. Tout `Cable()` a un `status=` (recupere via `Status.objects.get_for_model(Cable)`)
6. Les `UniqueConstraint` utilisent le prefixe `%(app_label)s_%(class)s_`
7. Pas de `count()` + `delete()` separes — utiliser la valeur de retour de `delete()`

### Vues et API

8. Les vues custom (`View`) ont `LoginRequiredMixin` + `PermissionRequiredMixin`
9. Chaque `permission_required` correspond au modele affiche (pas une permission generique)
10. Les ViewSets API ont tous les FK du serializer dans `select_related()`
11. Pas de serializer/code mort — supprimer tout ce qui n'est pas importe

### Jobs et signals

12. `post_migrate.connect()` a un `sender=` pour eviter les executions multiples
13. Pas de dependance inutile dans `pyproject.toml` — verifier les imports

### Tests

14. Les fixtures utilisent `validated_save()`, pas `.create()` ni `.save()`
15. Les tests FK filters utilisent des listes : `[str(device.pk)]`
16. Pas de `.configure(request)` sur les tables
17. Le job de test CI n'est PAS commente

### Nornir

18. `NornirSubTaskError.result` est un `MultiResult` (liste) — iterer pour extraire la root cause
19. Ne pas raise `RuntimeError` sur echec partiel — uniquement si `devices_success == 0`

### Python

20. Une seule fonction de normalisation par concept (DRY) — source de verite dans `models.py`
21. Pas d'imports circulaires entre modules jobs — partager via `_base.py` ou `utils.py`
22. Pas de bare `except Exception: pass` — toujours logger avant de continuer
23. Pas de `%` formatting dans les strings (hors `logger.*`) — utiliser f-strings

### Status et transitions

24. Ne jamais utiliser un status semantiquement incorrect comme fallback (ex: "Planned" pour oper-down)
25. Si un status cible n'existe pas, **skip la transition** (`None` → condition short-circuite)
26. Verifier que le status existe pour le bon content type (`dcim.interface`, pas juste `ipam.vrf`)

### Deploiement Docker

27. `pip install --upgrade` ne reinstalle pas si meme version — utiliser `--force-reinstall --no-deps`
28. Toujours `rm -rf /tmp/old` avant `docker cp` fresh — l'ancien `/tmp/` est stale
29. Toujours verifier le code installe avec `grep` apres deploy — le worker peut garder l'ancien code en memoire
