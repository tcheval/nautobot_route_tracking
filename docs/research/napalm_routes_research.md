# Recherche NAPALM — Collecte de routes réseau

**Date** : 2026-02-18
**Sources** : napalm.readthedocs.io, github.com/napalm-automation/napalm, nornir_napalm docs

---

## 1. `get_route_to()` — API complète

### Signature exacte

```python
def get_route_to(
    self,
    destination: str = "",
    protocol: str = "",
    longer: bool = False,
) -> Dict[str, List[RouteDict]]:
```

**Paramètres** :
- `destination` : Préfixe CIDR ex. `"1.0.0.0/24"` — chaîne vide = toutes les routes
- `protocol` : Filtre protocole ex. `"ospf"`, `"bgp"`, `"static"`, `"connected"` — chaîne vide = tous
- `longer` : Si `True`, retourne aussi les sous-préfixes plus spécifiques (support variable par driver)

### Format de retour exact

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

Retourne un **dict** de préfixes → **liste** de next-hops (ECMP possible). Chaque préfixe peut avoir plusieurs next-hops actifs ou inactifs.

---

## 2. Tous les champs du dict de route

| Champ | Type | Description |
| ----- | ---- | ----------- |
| `protocol` | `str` | `"BGP"`, `"OSPF"`, `"STATIC"`, `"CONNECTED"`, `"ISIS"`, `"RIP"`, `"EIGRP"`, `"LOCAL"` |
| `current_active` | `bool` | Route actuellement installée dans la FIB |
| `last_active` | `bool` | Était active lors du dernier changement |
| `age` | `int` | Âge en secondes |
| `preference` | `int` | Distance administrative (AD : OSPF=110, BGP=20/200, STATIC=1, CONNECTED=0) |
| `next_hop` | `str` | Adresse IP du next-hop (ex. `"172.17.17.17"`) |
| `outgoing_interface` | `str` | Interface de sortie (ex. `"GigabitEthernet0/1"`) |
| `selected_next_hop` | `bool` | Next-hop sélectionné parmi plusieurs candidats ECMP |
| `inactive_reason` | `str` | Raison d'inactivité (chaîne vide si actif) |
| `routing_table` | `str` | Nom VRF/table (`"default"`, `"inet.0"` sur JunOS, `"management"`, etc.) |
| `protocol_attributes` | `dict` | Attributs protocole-spécifiques (voir ci-dessous) |

### `protocol_attributes` par protocole

**BGP** :
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

**OSPF** :
```python
{
    "metric": 110,
    "metric_type": "2",  # "1" ou "2"
}
```

**STATIC / CONNECTED** :
```python
{}  # dict vide
```

---

## 3. Support par driver

| Driver | Plateforme | `get_route_to` | Notes |
| ------ | ---------- | -------------- | ----- |
| `eos` | Arista EOS | **Oui** | Inconsistances sur CONNECTED (next_hop parfois vide) |
| `ios` | Cisco IOS/IOS-XE | **Oui** | Bien supporté |
| `iosxr` | Cisco IOS-XR | **Oui** | Bien supporté |
| `junos` | Juniper JunOS | **Oui** | `routing_table="inet.0"` au lieu de `"default"` |
| `nxos` / `nxos_ssh` | Cisco NX-OS | **Oui** | Bien supporté |
| `panos` | Palo Alto PAN-OS | **Non** | `NotImplementedError` — driver communautaire sans implémentation |
| `sros` | Nokia SR-OS | Partiel | Support limité |

**Pour notre lab** : `cisco_ios` ✅, `arista_eos` ✅, `panos` ❌ (exclus du scope).

---

## 4. Exemples de retour par driver

### Arista EOS — OSPF route

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

### Cisco IOS — Static route

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

### Cisco IOS — ECMP BGP (2 next-hops)

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

## 5. Limitations critiques

### BGP full table — DANGER

- **Internet full table** : 900k+ routes en 2026 (IPv4 + IPv6)
- Ne **JAMAIS** appeler `get_route_to(destination="", protocol="")` sans filtre sur un PE router
- `get_route_to(destination="", protocol="bgp")` retourne des millions de lignes → timeout + OOM
- Nautobot worker : limite mémoire 768 MiB → OOM si BGP non filtré
- **Recommandation** : BGP exclu par défaut, avec `BooleanVar(default=False)` et avertissement explicite

### PAN-OS — Non supporté

```python
# napalm-panos community driver
def get_route_to(self, destination="", protocol="", longer=False):
    raise NotImplementedError("Feature not yet implemented.")
```

Exclure PAN-OS du scope de `nautobot_route_tracking`.

### JunOS — `routing_table` différent

- Retourne `"inet.0"` au lieu de `"default"` → stocker `routing_table` brut, pas transformer
- `longer=True` peut être ignoré silencieusement selon le driver

### Arista EOS — Routes CONNECTED

- `next_hop` parfois chaîne vide `""` pour CONNECTED routes (interface directement connectée)
- `outgoing_interface` contient l'interface dans ce cas
- Gérer `next_hop = ""` ou `next_hop = None` comme valeur valide

---

## 6. `get_bgp_neighbors()` — Alternative pour BGP peers

Pour collecter les sessions BGP sans les préfixes (moins de volumétrie) :

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

## 7. Recommandations pour `nautobot_route_tracking`

### Stratégie de collecte

1. **Méthode primaire** : `get_route_to()` via `nornir_napalm`
2. **Fallback** : Netmiko + TextFSM `show ip route` (même pattern que `collect_mac_arp.py`)
3. **BGP exclu par défaut** — ajouter `collect_bgp = BooleanVar(default=False)` avec warning
4. **Un appel par protocole activé** (OSPF, STATIC, CONNECTED séparément) pour contrôle granulaire

### Variables Job recommandées

```python
collect_ospf = BooleanVar(default=True, description="Collect OSPF routes")
collect_static = BooleanVar(default=True, description="Collect static routes")
collect_connected = BooleanVar(default=True, description="Collect connected routes")
collect_bgp = BooleanVar(
    default=False,
    description="Collect BGP routes (WARNING: may be slow/OOM on PE routers with full table)"
)
```

### Préfixes à exclure

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

### Valeurs de `protocol` normalisées

Pour éviter les variations entre drivers (EOS = `"OSPF"`, IOS = `"ospf"`, etc.), normaliser en lowercase :

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

Normalisation : `entry["protocol"].lower()` avant stockage.

---

## 8. Intégration Nornir — Pattern à utiliser

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

## 9. Usage dans `nautobot_netdb_tracking` — NAPALM getters utilisés

| Getter | Fichier | Usage |
| ------ | ------- | ----- |
| `get_mac_address_table` | `collect_mac_arp.py` | MAC table collection |
| `get_arp_table` | `collect_mac_arp.py` | ARP table collection |
| `get_interfaces` | `collect_mac_arp.py` | Interface state sync |
| `get_vlans` | `collect_mac_arp.py` | VLAN/switchport sync |
| `get_lldp_neighbors_detail` | `collect_topology.py` | LLDP neighbor discovery |

**`get_route_to`** n'est pas encore utilisé → c'est le nouveau getter à implémenter.

---

## 10. Modèle de données RouteEntry proposé

D'après les champs de `get_route_to()` :

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

**UniqueConstraint** : `(device, vrf, network, next_hop, protocol)` — ECMP = entrées séparées par next_hop.
