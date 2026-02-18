# Analyse des modèles — nautobot_netdb_tracking

**Fichier source analysé** : `nautobot_netdb_tracking/nautobot_netdb_tracking/models.py`
**Migrations analysées** : `0001_initial.py`, `0002_rename_constraints.py`, `0003_add_first_seen_indexes.py`
**Date d'analyse** : 2026-02-18

---

## 1. Vue d'ensemble

Le plugin expose **3 modèles principaux**, tous héritant de `PrimaryModel` (classe Nautobot) :

| Modèle | Table DB (déduite) | Rôle |
| ------ | ------------------ | ---- |
| `MACAddressHistory` | `nautobot_netdb_tracking_macaddresshistory` | Historique des adresses MAC vues sur les interfaces |
| `ARPEntry` | `nautobot_netdb_tracking_arpentry` | Entrées ARP collectées sur les devices |
| `TopologyConnection` | `nautobot_netdb_tracking_topologyconnection` | Connexions CDP/LLDP découvertes entre devices |

Un **helper module-level** est également défini : `normalize_mac_address()`.

---

## 2. Imports du fichier models.py

```python
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from nautobot.apps.models import PrimaryModel
from nautobot.dcim.models import Cable, Device, Interface
from nautobot.extras.models import Status
from nautobot.ipam.models import VLAN, IPAddress, Prefix
```

Points notables :
- `PrimaryModel` vient de `nautobot.apps.models` (pas de `nautobot.core.models`)
- `transaction` est importé pour les `transaction.atomic()` dans les méthodes `update_or_create_entry`
- `timezone` est utilisé pour `timezone.now()` dans `clean()` et `update_or_create_entry()`
- Tous les FK pointent vers des modèles Nautobot core : `Device`, `Interface`, `Cable`, `VLAN`, `IPAddress`, `Prefix`, `Status`

---

## 3. Fonction helper : `normalize_mac_address()`

```python
def normalize_mac_address(mac: str) -> str:
    if not mac:
        raise ValidationError("MAC address cannot be empty")
    clean_mac = mac.upper().replace(":", "").replace("-", "").replace(".", "")
    if len(clean_mac) != 12 or not all(c in "0123456789ABCDEF" for c in clean_mac):
        raise ValidationError(f"Invalid MAC address format: {mac}")
    return ":".join(clean_mac[i : i + 2] for i in range(0, 12, 2))
```

- Accepte `:`, `-`, `.` ou sans séparateur ; convertit en MAJUSCULES
- Produit le format `XX:XX:XX:XX:XX:XX` (17 caractères)
- Lève `ValidationError` si vide ou format invalide (longueur != 12 ou caractères hors hex)

---

## 4. Modèle : `MACAddressHistory`

### 4.1 Héritage

```python
class MACAddressHistory(PrimaryModel):
```

`PrimaryModel` fournit automatiquement (confirmé via `0001_initial.py`) :
- `id` : `UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False, unique=True)`
- `created` : `DateTimeField(auto_now_add=True, null=True)`
- `last_updated` : `DateTimeField(auto_now=True, null=True)`
- `_custom_field_data` : `JSONField(blank=True, default=dict, encoder=DjangoJSONEncoder)`
- `tags` : `TagsField(through='extras.TaggedItem', to='extras.Tag')`
- Mixins : `DataComplianceModelMixin`, `DynamicGroupMixin`, `NotesMixin`

### 4.2 Champs

| Champ | Type Django exact | Options | Notes |
| ----- | ----------------- | ------- | ----- |
| `device` | `ForeignKey(to=Device, ...)` | `on_delete=CASCADE`, `related_name="mac_address_history"` | Obligatoire |
| `interface` | `ForeignKey(to=Interface, ...)` | `on_delete=CASCADE`, `related_name="mac_address_history"` | Obligatoire |
| `mac_address` | `CharField(max_length=17)` | — | Format `XX:XX:XX:XX:XX:XX` |
| `vlan` | `ForeignKey(to=VLAN, ...)` | `on_delete=SET_NULL`, `related_name="mac_address_history"`, `null=True`, `blank=True` | Optionnel |
| `first_seen` | `DateTimeField(auto_now_add=True)` | — | Géré automatiquement à la création |
| `last_seen` | `DateTimeField()` | — | Pas de `auto_now`, pas de `default` — fourni manuellement |

### 4.3 `natural_key_field_lookups`

```python
natural_key_field_lookups = ["device__name", "interface__name", "mac_address"]
```

### 4.4 Meta class exacte

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

- `verbose_name_plural` identique à `verbose_name` (intentionnel)
- `UniqueConstraint` sur 4 champs — `vlan=NULL` traité comme une valeur distincte par PostgreSQL
- Nom de contrainte : `<app_label>_<model_lower>_<description>` (renommé en migration `0002`)
- 5 index totaux — l'index sur `first_seen` ajouté en migration `0003`

### 4.5 `__str__()`

```python
def __str__(self) -> str:
    vlan_str = f" (VLAN {self.vlan.vid})" if self.vlan else ""
    return f"{self.mac_address} on {self.device.name}:{self.interface.name}{vlan_str}"
```

### 4.6 `clean()` exact

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

### 4.7 `update_or_create_entry()` — Pattern NetDB CRITIQUE

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

## 5. Modèle : `ARPEntry`

### 5.1 Champs

| Champ | Type Django exact | Options | Notes |
| ----- | ----------------- | ------- | ----- |
| `device` | `ForeignKey(to=Device, ...)` | `on_delete=CASCADE`, `related_name="arp_entries"` | Obligatoire |
| `interface` | `ForeignKey(to=Interface, ...)` | `on_delete=SET_NULL`, `related_name="arp_entries"`, `null=True`, `blank=True` | Optionnel |
| `ip_address` | `GenericIPAddressField(protocol="both")` | — | Accepte IPv4 et IPv6 |
| `ip_address_object` | `ForeignKey(to="ipam.IPAddress", ...)` | `on_delete=SET_NULL`, `related_name="arp_entries"`, `null=True`, `blank=True` | Auto-résolu vers IPAM |
| `mac_address` | `CharField(max_length=17)` | — | Format `XX:XX:XX:XX:XX:XX` |
| `first_seen` | `DateTimeField(auto_now_add=True)` | — | Géré automatiquement |
| `last_seen` | `DateTimeField()` | — | Fourni manuellement |

### 5.2 Meta class exacte

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

- Utilise `host=ip_str` (API Nautobot 3.x, pas `address=`)
- `parent=prefix` (Nautobot 3.x, pas `namespace=`)

---

## 6. Modèle : `TopologyConnection`

### 6.1 Inner class `Protocol` (TextChoices)

```python
class Protocol(models.TextChoices):
    CDP = "CDP", "CDP"
    LLDP = "LLDP", "LLDP"
```

### 6.2 Champs

| Champ | Type Django exact | Options | Notes |
| ----- | ----------------- | ------- | ----- |
| `local_device` | `ForeignKey(to=Device, ...)` | `on_delete=CASCADE`, `related_name="topology_connections_local"` | Obligatoire |
| `local_interface` | `ForeignKey(to=Interface, ...)` | `on_delete=CASCADE`, `related_name="topology_connections_local"` | Obligatoire |
| `remote_device` | `ForeignKey(to=Device, ...)` | `on_delete=CASCADE`, `related_name="topology_connections_remote"` | Obligatoire |
| `remote_interface` | `ForeignKey(to=Interface, ...)` | `on_delete=CASCADE`, `related_name="topology_connections_remote"` | Obligatoire |
| `protocol` | `CharField(max_length=10, choices=Protocol.choices)` | — | `"CDP"` ou `"LLDP"` |
| `cable` | `ForeignKey(to=Cable, ...)` | `on_delete=SET_NULL`, `related_name="topology_connections"`, `null=True`, `blank=True` | Optionnel |
| `first_seen` | `DateTimeField(auto_now_add=True)` | — | Géré automatiquement |
| `last_seen` | `DateTimeField()` | — | Fourni manuellement |

### 6.3 Meta class exacte

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

### 6.5 `clean()` exact

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

## 7. Pattern `first_seen` / `last_seen`

| Champ | Configuration Django | Gestion |
| ----- | -------------------- | ------- |
| `first_seen` | `DateTimeField(auto_now_add=True)` | Django le remplit automatiquement, non modifiable |
| `last_seen` | `DateTimeField()` | Pas de `auto_now`, pas de `default` — géré manuellement |

### Algorithme NetDB UPDATE vs INSERT

```
Pour chaque donnée collectée sur un device :
  1. Normaliser la donnée clé (MAC, IP, etc.)
  2. Chercher un enregistrement existant avec la même combinaison de clés métier
  3. Si trouvé → UPDATE last_seen = now() (+ champs annexes si changés)
  4. Si non trouvé → INSERT nouvelle ligne (first_seen = auto, last_seen = now())

Résultat :
  - Une donnée stable pendant 90 jours → 1 seul enregistrement
    (first_seen = date initiale, last_seen = date du dernier scan)
  - Une donnée qui change → nouvel enregistrement avec first_seen = date du changement
```

---

## 8. Règles critiques pour recréer un modèle similaire

1. Toujours appeler `super().clean()` en premier dans `clean()`
2. Toujours utiliser `validated_save()` — jamais `.save()` direct
3. Envelopper les opérations DB dans `transaction.atomic()`
4. Comparer les FK par `_id` (ex. `self.interface.device_id != self.device_id`) pour éviter les requêtes supplémentaires
5. `last_seen` sans `auto_now` ni `default` → géré manuellement dans `update_or_create_entry()`, initialisé dans `clean()` comme fallback
6. `first_seen` avec `auto_now_add=True` → géré par Django, ne pas tenter de le modifier
7. `related_name` explicite sur tous les FK — obligatoire quand deux FK pointent vers le même modèle
8. Noms de contraintes : convention `<app_label>_<model_class_lower>_<description>` — à respecter dès la migration initiale
9. `natural_key_field_lookups` requis par Nautobot pour les imports/exports naturels
10. `PrimaryModel` vient de `nautobot.apps.models` (pas `nautobot.core.models`)
