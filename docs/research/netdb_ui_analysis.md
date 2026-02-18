# Analyse des composants UI — nautobot_netdb_tracking

**Fichiers analysés** : `filters.py`, `tables.py`, `views.py`, `forms.py`, `urls.py`, `navigation.py`, `template_content.py`, `templates/`
**Date d'analyse** : 2026-02-18

---

## 1. filters.py

### Imports

```python
import django_filters
from nautobot.apps.filters import NaturalKeyOrPKMultipleChoiceFilter, NautobotFilterSet, SearchFilter
from nautobot.dcim.models import Device, Interface, Location
from nautobot.extras.models import Role, Status
from nautobot.ipam.models import VLAN, IPAddress
from nautobot_netdb_tracking.models import ARPEntry, MACAddressHistory, TopologyConnection
```

### `MACAddressHistoryFilterSet(NautobotFilterSet)`

**q (SearchFilter)** : prédicats sur `mac_address`, `device__name`, `interface__name`, `vlan__name` — tous `icontains`.

| Champ | Type | `to_field_name` | `field_name` |
| ----- | ---- | --------------- | ------------ |
| `device` | `NaturalKeyOrPKMultipleChoiceFilter` | `"name"` | direct |
| `device_role` | `NaturalKeyOrPKMultipleChoiceFilter` | `"name"` | `"device__role"` |
| `interface` | `NaturalKeyOrPKMultipleChoiceFilter` | `"name"` | direct |
| `vlan` | `NaturalKeyOrPKMultipleChoiceFilter` | `"vid"` | direct (vid, pas pk) |
| `mac_address` | `django_filters.CharFilter` | n/a | method custom |
| `location` | `NaturalKeyOrPKMultipleChoiceFilter` | `"name"` | `"device__location"` |
| `first_seen_after` | `django_filters.DateTimeFilter` | n/a | `"first_seen"`, `gte` |
| `first_seen_before` | `django_filters.DateTimeFilter` | n/a | `"first_seen"`, `lte` |
| `last_seen_after` | `django_filters.DateTimeFilter` | n/a | `"last_seen"`, `gte` |
| `last_seen_before` | `django_filters.DateTimeFilter` | n/a | `"last_seen"`, `lte` |

Meta : `model=MACAddressHistory`, `fields=[...]`

### `ARPEntryFilterSet(NautobotFilterSet)`

Mêmes filtres + additions :

| Champ | Type | Notes |
| ----- | ---- | ----- |
| `ip_address` | `django_filters.CharFilter` | `lookup_expr="icontains"` — bare string |
| `ip_address_object` | `NaturalKeyOrPKMultipleChoiceFilter` | `queryset=IPAddress`, `to_field_name="host"` |
| `has_ip_object` | `django_filters.BooleanFilter` | `field_name="ip_address_object"`, `lookup_expr="isnull"`, `exclude=True` |

### `TopologyConnectionFilterSet(NautobotFilterSet)`

Paires symétriques local/remote pour device, device_role, interface. Plus :

| Champ | Type | Notes |
| ----- | ---- | ----- |
| `protocol` | `django_filters.MultipleChoiceFilter` | `choices=TopologyConnection.Protocol.choices` |
| `has_cable` | `django_filters.BooleanFilter` | `field_name="cable"`, `isnull`, `exclude=True` |
| `location` | `NaturalKeyOrPKMultipleChoiceFilter` | `field_name="local_device__location"` |
| `remote_location` | `NaturalKeyOrPKMultipleChoiceFilter` | `field_name="remote_device__location"` |

### Format d'input CRITIQUE (tests)

```python
# NaturalKeyOrPKMultipleChoiceFilter REQUIRES list input
filterset = MACAddressHistoryFilterSet({"device": [str(device.pk)]})
filterset = MACAddressHistoryFilterSet({"vlan": [str(vlan.vid)]})  # vid, pas pk

# CharFilter / SearchFilter prennent des bare strings
filterset = MACAddressHistoryFilterSet({"mac_address": "00:11:22"})
filterset = ARPEntryFilterSet({"ip_address": "192.168"})
```

---

## 2. tables.py

### Imports

```python
import django_tables2 as tables
from nautobot.apps.tables import BaseTable, ButtonsColumn, ToggleColumn
```

### `MACAddressHistoryTable(BaseTable)`

| Colonne | Type | Détails |
| ------- | ---- | ------- |
| `pk` | `ToggleColumn` | bulk checkbox |
| `device` | `tables.Column` | `linkify=True` |
| `interface` | `tables.Column` | `linkify=True` |
| `mac_address` | `tables.Column` | `attrs={"td": {"class": "text-nowrap"}}` |
| `vlan` | `tables.Column` | `linkify=True` |
| `first_seen` | `tables.DateTimeColumn` | `format="Y-m-d H:i"` |
| `last_seen` | `tables.DateTimeColumn` | `format="Y-m-d H:i"` |
| `port_status` | `tables.Column` | `accessor="interface__status"` |
| `port_description` | `tables.Column` | `accessor="interface__description"` |
| `actions` | `ButtonsColumn(MACAddressHistory)` | |

Meta : `model=MACAddressHistory`. `default_columns` exclut `first_seen`.

### Variantes

- `MACAddressHistoryDeviceTable(BaseTable)` : sans `device` et `actions` — utilisée sur Device detail tab
- `MACAddressHistoryInterfaceTable(BaseTable)` : sans `device`, `interface`, `port_status`, `actions` — utilisée sur Interface detail tab

### `ARPEntryTable(BaseTable)`

Colonnes : `pk`, `device`, `interface`, `ip_address` (linkify conditionnel vers `ip_address_object.get_absolute_url()`), `mac_address`, `first_seen`, `last_seen`, `actions`.

`default_columns` omet `interface` et `first_seen`.

### `TopologyConnectionTable(BaseTable)`

Colonnes : `pk`, `local_device`, `local_interface`, `remote_device`, `remote_interface`, `protocol`, `cable`, `first_seen`, `last_seen`, `actions`. Tous device/interface/cable avec `linkify=True`.

### PIÈGE : Tables dict-based

```python
# CORRECT — pour tables sans modèle (données dict)
class SwitchReportTable(tables.Table):
    class Meta:
        template_name = "inc/table.html"  # explicitement requis

# WRONG — crash sur CustomField.objects.get_for_model() sans modèle
class SwitchReportTable(BaseTable):
    ...
```

---

## 3. views.py

### `MACAddressHistoryUIViewSet(NautobotUIViewSet)`

```python
queryset = MACAddressHistory.objects.select_related(
    "device", "device__location", "interface", "interface__status", "vlan"
).prefetch_related("tags")
filterset_class = MACAddressHistoryFilterSet
filterset_form_class = MACAddressHistoryFilterForm
table_class = MACAddressHistoryTable
form_class = MACAddressHistoryForm
serializer_class = MACAddressHistorySerializer
action_buttons = ("export",)
lookup_field = "pk"
```

### `ARPEntryUIViewSet(NautobotUIViewSet)`

```python
queryset = ARPEntry.objects.select_related(
    "device", "device__location", "interface", "ip_address_object"
).prefetch_related("tags")
```

### `TopologyConnectionUIViewSet(NautobotUIViewSet)`

```python
queryset = TopologyConnection.objects.select_related(
    "local_device", "local_device__location", "local_interface",
    "remote_device", "remote_device__location", "remote_interface", "cable"
).prefetch_related("tags")
```

### Tab Views (pattern commun)

Toutes héritent `LoginRequiredMixin, PermissionRequiredMixin, View`. Toutes utilisent `get_paginate_count(request)` + `EnhancedPaginator` via `RequestConfig`.

```python
from nautobot.core.views.paginator import EnhancedPaginator, get_paginate_count

per_page = get_paginate_count(request)
RequestConfig(
    request,
    paginate={"per_page": per_page, "paginator_class": EnhancedPaginator},
).configure(table)
```

| Classe | Permission | Template | Table |
| ------ | ---------- | -------- | ----- |
| `DeviceMACTabView` | `view_macaddresshistory` | `device_mac_tab.html` | `MACAddressHistoryDeviceTable` |
| `DeviceARPTabView` | `view_arpentry` | `device_arp_tab.html` | `ARPEntryDeviceTable` |
| `DeviceTopologyTabView` | `view_topologyconnection` | `device_topology_tab.html` | `TopologyConnectionDeviceTable` |
| `InterfaceMACTabView` | `view_macaddresshistory` | `interface_mac_tab.html` | `MACAddressHistoryInterfaceTable` |

`DeviceTopologyTabView` utilise `Q(local_device=device) | Q(remote_device=device)`.

---

## 4. urls.py

```python
from nautobot.apps.urls import NautobotUIViewSetRouter

app_name = "nautobot_netdb_tracking"

router = NautobotUIViewSetRouter()
router.register("mac-address-history", MACAddressHistoryUIViewSet)
router.register("arp-entries", ARPEntryUIViewSet)
router.register("topology-connections", TopologyConnectionUIViewSet)

urlpatterns = [
    path("dashboard/",                          NetDBDashboardView.as_view(),     name="dashboard"),
    path("devices/<uuid:pk>/mac-addresses/",    DeviceMACTabView.as_view(),       name="device_mac_tab"),
    path("devices/<uuid:pk>/arp-entries/",      DeviceARPTabView.as_view(),       name="device_arp_tab"),
    path("devices/<uuid:pk>/topology/",         DeviceTopologyTabView.as_view(),  name="device_topology_tab"),
    path("interfaces/<uuid:pk>/mac-addresses/", InterfaceMACTabView.as_view(),    name="interface_mac_tab"),
]
urlpatterns += router.urls
```

**app_name obligatoire** pour les noms de routes (`{% url 'nautobot_netdb_tracking:...' %}`).

---

## 5. navigation.py

```
NavMenuTab: "NetDB Tracking" (weight=500)
+-- NavMenuGroup: "Topology" (weight=200)
    NavMenuItem "Topology Connections" → topologyconnection_list, perm: view_topologyconnection
    NavMenuAddButton → topologyconnection_add, perm: add_topologyconnection
```

MAC History et ARP Entries n'ont **pas** de NavMenuItem — accès via Dashboard et tabs.

Pattern de permissions sur les items : `permissions=["nautobot_netdb_tracking.view_topologyconnection"]`.

---

## 6. template_content.py

```python
from nautobot.apps.ui import TemplateExtension

template_extensions = [DeviceNetDBTab, InterfaceNetDBTab]
```

### `DeviceNetDBTab` (`model="dcim.device"`)

- `detail_tabs()` : 3 onglets — "MAC Addresses", "ARP Entries", "Topology"
  - Chaque onglet = `{"title": "...", "url": reverse("nautobot_netdb_tracking:device_mac_tab", kwargs={"pk": self.context["object"].pk})}`
- `right_page()` : 3 COUNT queries → rendu `inc/device_netdb_panel.html` avec `mac_count`, `arp_count`, `topology_count`

### `InterfaceNetDBTab` (`model="dcim.interface"`)

- `detail_tabs()` : 1 onglet — "MAC Addresses"
- `right_page()` : 4 queries, rendu `inc/interface_netdb_panel.html`

---

## 7. Templates — Patterns critiques

### Fichiers (liste complète)

```
templates/nautobot_netdb_tracking/
├── dashboard.html
├── device_mac_tab.html
├── device_arp_tab.html
├── device_topology_tab.html
├── interface_mac_tab.html
└── inc/
    ├── device_netdb_panel.html
    └── interface_netdb_panel.html
```

### Tab templates — Structure exacte

```django
{% extends "generic/object_detail.html" %}
{% load render_table from django_tables2 %}

{% block content %}
<div class="card">
  <div class="card-header"><strong>MAC Addresses</strong></div>
  <div class="card-body">
    {% if table.data %}
      {% render_table table "inc/table.html" %}
      {% include 'inc/paginator.html' with paginator=table.paginator page=table.page %}
    {% else %}
      <p class="text-muted mb-0">No data available.</p>
    {% endif %}
  </div>
  {% if table.data %}
  <div class="card-footer">
    <a href="{% url 'nautobot_netdb_tracking:macaddresshistory_list' %}?device={{ object.pk }}">
      View all →
    </a>
  </div>
  {% endif %}
</div>
{% endblock %}
```

**CRITIQUE** : Les tabs étendent `generic/object_detail.html` (pas `base.html`).

### Dashboard / Report templates — Structure

```django
{% extends "base.html" %}
{% load helpers humanize %}
{% load render_table from django_tables2 %}

{% block title %}Switch Report{% endblock %}
{% block breadcrumbs %}{% endblock %}

{% block content %}
  ...cards statistiques...
  {% render_table table "inc/table.html" %}
  {# Pour dict-based table avec paginator manuel : #}
  {% include 'inc/paginator.html' with paginator=paginator page=page %}
  {# Pour table RequestConfig : #}
  {% include 'inc/paginator.html' with paginator=table.paginator page=table.page %}
{% endblock %}
```

### Panel templates (inc/)

```django
{% load helpers %}
<div class="card">...</div>
```

Pas de `{% extends %}`, pas de `{% block %}` — rendus via `TemplateExtension.right_page()`.

---

## 8. Patterns critiques — Récapitulatif

### Toujours `inc/table.html`

```django
{% render_table table "inc/table.html" %}              {# CORRECT #}
{% render_table table "django_tables2/bootstrap5.html" %}  {# WRONG #}
```

### Toujours `EnhancedPaginator` + `inc/paginator.html`

```python
# Dans la vue
from nautobot.core.views.paginator import EnhancedPaginator, get_paginate_count
per_page = get_paginate_count(request)
RequestConfig(request, paginate={"per_page": per_page, "paginator_class": EnhancedPaginator}).configure(table)
```

```django
{% include 'inc/paginator.html' with paginator=table.paginator page=table.page %}
```

### `{% load %}` sur lignes séparées

```django
{% load helpers humanize %}
{% load render_table from django_tables2 %}
```

Jamais : `{% load helpers humanize render_table from django_tables2 %}` — Django misparse `from`.

### Pas de `<h1>` dans `{% block content %}`

`{% block title %}` suffit — Nautobot rend le `<h1>` via `inc/page_title.html`.

### Breadcrumbs vides sur les pages liste/dashboard

```django
{% block breadcrumbs %}{% endblock %}
```

### Tabs héritent de `generic/object_detail.html`

```django
{% extends "generic/object_detail.html" %}  {# CORRECT pour les tabs #}
{% extends "base.html" %}                   {# WRONG pour les tabs #}
```

### `block.super` dans le bloc javascript

```django
{% block javascript %}{{ block.super }}<script>...</script>{% endblock %}
```

### `NautobotUIViewSet` — Attributs obligatoires

```python
class RouteEntryUIViewSet(NautobotUIViewSet):
    queryset = RouteEntry.objects.select_related("device", "device__location", "vrf").prefetch_related("tags")
    filterset_class = RouteEntryFilterSet
    table_class = RouteEntryTable
    action_buttons = ("export",)
```

### `NaturalKeyOrPKMultipleChoiceFilter` — Input format

```python
# FK filters → liste de strings (pk ou natural key)
filterset = RouteEntryFilterSet({"device": [str(device.pk)]})
filterset = RouteEntryFilterSet({"vrf": [str(vrf.pk)]})

# CharFilter → bare string
filterset = RouteEntryFilterSet({"network": "10.0.0"})
filterset = RouteEntryFilterSet({"q": "search term"})
```

---

## 9. API (api/)

### `api/serializers.py`

```python
from nautobot.apps.api import NautobotModelSerializer

class MACAddressHistorySerializer(NautobotModelSerializer):
    class Meta:
        model = MACAddressHistory
        fields = "__all__"
```

### `api/views.py`

```python
from nautobot.apps.api import NautobotModelViewSet

class MACAddressHistoryViewSet(NautobotModelViewSet):
    queryset = MACAddressHistory.objects.select_related(
        "device", "interface", "vlan"
    ).prefetch_related("tags")
    serializer_class = MACAddressHistorySerializer
    filterset_class = MACAddressHistoryFilterSet
```

### `api/urls.py`

```python
from nautobot.apps.routers import OrderedDefaultRouter

router = OrderedDefaultRouter()
router.register("mac-address-history", MACAddressHistoryViewSet)
router.register("arp-entries", ARPEntryViewSet)
router.register("topology-connections", TopologyConnectionViewSet)

urlpatterns = router.urls
```

**Note** : `OrderedDefaultRouter` (pas `DefaultRouter`) pour garantir l'ordre stable des routes.
