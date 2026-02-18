# Structure Standard d'un Plugin Nautobot 3.x

Document de recherche basé sur :

- [cookiecutter-nautobot-app](https://github.com/nautobot/cookiecutter-nautobot-app) (template officiel Network to Code)
- [NautobotAppConfig Documentation](https://docs.nautobot.com/projects/core/en/stable/development/apps/api/nautobot-app-config/)
- [App Setup Documentation](https://docs.nautobot.com/projects/core/en/stable/development/apps/api/setup/)
- Le plugin de référence `nautobot_netdb_tracking` (fonctionnel et éprouvé en production)

---

## 1. Structure de Fichiers Standard

### Arborescence Complète Générée par Cookiecutter

```
nautobot-app-<app_slug>/                   # Répertoire racine du projet (repo git)
├── .github/
│   ├── CODEOWNERS
│   └── workflows/
│       ├── ci.yml
│       └── changelog.yml
├── .gitignore
├── .readthedocs.yaml
├── .yamllint.yml
├── changes/                               # Changelog entries (towncrier)
├── development/
│   ├── docker-compose.yml
│   └── nautobot_config.py
├── docs/
│   ├── admin/
│   ├── dev/
│   └── user/
├── invoke.example.yml
├── mkdocs.yml
├── pyproject.toml                         # Configuration du projet (Poetry)
├── README.md
├── tasks.py                               # Invoke tasks
│
└── <app_name>/                            # Package Python (snake_case)
    ├── __init__.py                        # NautobotAppConfig — OBLIGATOIRE
    ├── admin.py                           # Django Admin Interface
    ├── api/
    │   ├── __init__.py
    │   ├── serializers.py                 # REST API serializers
    │   ├── urls.py                        # REST API URL patterns
    │   └── views.py                       # REST API viewsets
    ├── banner.py                          # Custom banner (optionnel)
    ├── custom_validators.py               # Custom validators (optionnel)
    ├── datasources.py                     # Git datasources (optionnel)
    ├── filter_extensions.py               # Filter extensions (optionnel)
    ├── filters.py                         # FilterSets UI/API/GraphQL
    ├── forms.py                           # UI Forms et Filter Forms
    ├── graphql/
    │   └── types.py                       # GraphQL Type Objects (optionnel)
    ├── homepage.py                        # Home Page Content (optionnel)
    ├── jinja_filters.py                   # Jinja2 filters (optionnel)
    ├── jobs/
    │   ├── __init__.py                    # register_jobs() — OBLIGATOIRE si jobs
    │   ├── _base.py                       # Classe de base commune (convention)
    │   └── my_job.py
    ├── middleware.py                       # Django middleware (optionnel)
    ├── migrations/
    │   ├── __init__.py
    │   └── 0001_initial.py
    ├── models.py                          # Modèles Django
    ├── navigation.py                      # Navigation menu items
    ├── secrets.py                         # Secret providers (optionnel)
    ├── signals.py                         # Signal handlers
    ├── static/
    │   └── <app_name>/
    │       ├── css/
    │       └── js/
    ├── table_extensions.py                # Extending core tables (optionnel)
    ├── template_content.py                # TemplateExtension (tabs, panels)
    ├── templates/
    │   └── <app_name>/
    │       ├── inc/                       # Partial templates (panels, tabs)
    │       └── *.html
    ├── urls.py                            # UI URL patterns
    └── views.py                           # UI views
│
└── tests/
    ├── __init__.py
    ├── conftest.py                        # Pytest fixtures
    ├── test_settings.py                   # Django settings pour les tests
    ├── test_models.py
    ├── test_filters.py
    ├── test_views.py
    ├── test_api.py
    └── test_jobs.py
```

### Fichiers Obligatoires vs Optionnels

| Fichier | Statut | Raison |
| ------- | ------ | ------ |
| `<app_name>/__init__.py` | **OBLIGATOIRE** | Contient NautobotAppConfig |
| `pyproject.toml` | **OBLIGATOIRE** | Configuration et dépendances |
| `<app_name>/migrations/__init__.py` | **OBLIGATOIRE** | Django nécessite le package |
| `<app_name>/migrations/0001_initial.py` | **OBLIGATOIRE** si modèles | Créé par `makemigrations` |
| `<app_name>/models.py` | Très recommandé | Presque toujours nécessaire |
| `<app_name>/filters.py` | Très recommandé | UI et API filtering |
| `<app_name>/forms.py` | Très recommandé | UI forms |
| `<app_name>/views.py` | Très recommandé | UI views |
| `<app_name>/urls.py` | Très recommandé | UI URL routing |
| `<app_name>/navigation.py` | Très recommandé | Menu Nautobot |
| `<app_name>/api/` | Très recommandé | REST API standard |
| `<app_name>/tables.py` | Très recommandé | Affichage des listes |
| `<app_name>/jobs/` | Optionnel | Seulement si automatisation |
| `<app_name>/signals.py` | Optionnel | Hooks post_migrate |
| `<app_name>/template_content.py` | Optionnel | Tabs/panels sur vues core |
| `<app_name>/static/` | Optionnel | CSS/JS custom |
| `<app_name>/templates/` | Optionnel | HTML custom |
| `<app_name>/admin.py` | Optionnel | Django admin |
| `<app_name>/banner.py` | Optionnel | Bannière UI |
| `<app_name>/middleware.py` | Optionnel | Django middleware custom |
| `<app_name>/jinja_filters.py` | Optionnel | Filtres Jinja2 custom |
| `<app_name>/graphql/` | Optionnel | Types GraphQL custom |
| `<app_name>/custom_validators.py` | Optionnel | Validators sur modèles core |
| `<app_name>/datasources.py` | Optionnel | Git datasources |
| `<app_name>/secrets.py` | Optionnel | Secret providers custom |
| `<app_name>/homepage.py` | Optionnel | Widgets home page |
| `tests/` | **OBLIGATOIRE** | Standard NTC : ≥80% coverage |
| `README.md` | **OBLIGATOIRE** | Documentation minimale |

### Conventions de Nommage

| Artefact | Convention | Exemple |
| -------- | ---------- | ------- |
| Package Python (`app_name`) | `snake_case` | `nautobot_route_tracking` |
| Nom du projet (`project_slug`) | `kebab-case` | `nautobot-app-route-tracking` |
| Nom PyPI (`name` dans pyproject) | `kebab-case` | `nautobot-route-tracking` |
| `base_url` dans NautobotAppConfig | `kebab-case` | `route-tracking` |
| Classe NautobotAppConfig | `PascalCase` | `NautobotRouteTrackingConfig` |
| Modèles Django | `PascalCase` | `RouteEntry`, `RouteHistory` |
| Tables django-tables2 | `PascalCase` + `Table` | `RouteEntryTable` |
| FilterSets | `PascalCase` + `FilterSet` | `RouteEntryFilterSet` |
| Serializers | `PascalCase` + `Serializer` | `RouteEntrySerializer` |
| ViewSets API | `PascalCase` + `ViewSet` | `RouteEntryViewSet` |
| ViewSets UI | `PascalCase` + `UIViewSet` | `RouteEntryUIViewSet` |

---

## 2. NautobotAppConfig (`__init__.py`)

### Attributs Obligatoires

Ces 6 attributs doivent être définis dans toute sous-classe de `NautobotAppConfig` :

| Attribut | Type | Description | Exemple |
| -------- | ---- | ----------- | ------- |
| `name` | `str` | Nom du package Python (identique au répertoire source) | `"nautobot_route_tracking"` |
| `verbose_name` | `str` | Nom human-readable affiché dans l'UI | `"Route Tracking"` |
| `version` | `str` | Version semver du plugin | `"1.0.0"` |
| `author` | `str` | Nom de l'auteur ou organisation | `"Thomas"` |
| `author_email` | `str` | Email de contact public | `"thomas@networktocode.com"` |
| `description` | `str` | Courte description du plugin | `"Track IP routes from network devices"` |

### Attributs Optionnels Importants

| Attribut | Type | Défaut | Description |
| -------- | ---- | ------ | ----------- |
| `base_url` | `str` | Identique à `name` | Préfixe URL pour toutes les routes du plugin. **Utiliser kebab-case** (ex: `"route-tracking"`). Différent du `name` qui est en snake_case. |
| `required_settings` | `list[str]` | `[]` | Settings qui **doivent** être dans `PLUGINS_CONFIG[app_name]`. Si absent, Nautobot refuse de démarrer. |
| `default_settings` | `dict` | `{}` | Valeurs par défaut des settings optionnels. Fusionnées avec `PLUGINS_CONFIG[app_name]`. |
| `min_version` | `str \| None` | `None` | Version Nautobot minimale requise (ex: `"3.0.6"`). Vérifiée au démarrage. |
| `max_version` | `str \| None` | `None` | Version Nautobot maximale compatible (ex: `"3.99"`). |
| `middleware` | `list[str]` | `[]` | Classes de middleware Django à ajouter après le middleware core Nautobot. |
| `installed_apps` | `list[str]` | `[]` | Apps Django additionnelles à activer automatiquement (ex: dépendances qui ne sont pas des plugins). |
| `provides_dynamic_jobs` | `bool` | `False` | Active le rechargement du code des jobs à chaque exécution. |
| `searchable_models` | `list[str]` | `[]` | Modèles inclus dans la recherche globale Nautobot. Format : `["app_label.ModelName"]`. |
| `constance_config` | `dict` | `{}` | Settings dynamiques via Django Constance (stockés en DB, modifiables sans redémarrage). |

### Attributs de Localisation de Modules

Ces attributs sont des **chemins Python dotted** vers les modules contenant les features correspondantes. Nautobot les charge automatiquement.

| Attribut | Module cible | Exemple |
| -------- | ------------ | ------- |
| `banner_function` | Fonction de bannière | `"nautobot_route_tracking.banner.banner_message"` |
| `custom_validators` | Liste de classes validators | `"nautobot_route_tracking.custom_validators"` |
| `jinja_filters` | Module de filtres Jinja2 | `"nautobot_route_tracking.jinja_filters"` |
| `jobs` | Module contenant les jobs | `"nautobot_route_tracking.jobs"` |
| `menu_items` | Variable `menu_items` dans navigation.py | Automatiquement détecté via `navigation.py` |
| `template_extensions` | Liste de classes TemplateExtension | `"nautobot_route_tracking.template_content"` |

**Note** : En pratique avec Nautobot 3.x, `jobs` n'est pas nécessaire dans `NautobotAppConfig` si `register_jobs()` est appelé dans `jobs/__init__.py`.

### Méthode `ready()`

La méthode `ready()` est appelée par Django quand l'app est entièrement initialisée (après le chargement de toutes les apps). C'est le bon endroit pour :

1. **Importer et connecter les signals Django** — doit être fait ici car les modèles sont disponibles
2. **Corriger le grouping des jobs** — Nautobot réinitialise le grouping à chaque démarrage
3. **Enregistrer des callbacks** — hooks sur d'autres apps
4. **Jamais** importer des modèles au niveau module du plugin (risque de circular imports)

```python
def ready(self) -> None:
    """Hook appelé quand Django est entièrement initialisé."""
    super().ready()  # TOUJOURS appeler super().ready() en premier

    # Import des signals (DOIT être dans ready(), pas au niveau module)
    from nautobot_route_tracking.signals import register_signals
    register_signals(sender=self.__class__)

    # Fix du grouping des jobs (Nautobot le réinitialise au démarrage)
    self._fix_job_grouping()

@staticmethod
def _fix_job_grouping() -> None:
    """Corrige le grouping des jobs après chaque démarrage."""
    from django.db import OperationalError, ProgrammingError
    try:
        from nautobot.extras.models import Job
        Job.objects.filter(
            module_name__startswith="nautobot_route_tracking.jobs"
        ).update(grouping="Route Tracking")
    except (OperationalError, ProgrammingError):
        # Tables inexistantes lors de la migration initiale
        pass
```

**Piège critique** : Toujours entourer les accès ORM dans `ready()` par un try/except `(OperationalError, ProgrammingError)`. Les tables peuvent ne pas exister encore lors de la première migration.

### Pattern `register_jobs()` dans `jobs/__init__.py`

En Nautobot 3.x, les jobs **ne sont pas auto-enregistrés**. Il faut appeler `register_jobs()` explicitement depuis `nautobot.core.celery` :

```python
# nautobot_route_tracking/jobs/__init__.py
from nautobot.core.celery import register_jobs

from nautobot_route_tracking.jobs.collect_routes import CollectRoutesJob
from nautobot_route_tracking.jobs.purge_old_data import PurgeOldDataJob

jobs = [CollectRoutesJob, PurgeOldDataJob]

register_jobs(*jobs)
```

Ce fichier est exécuté au démarrage. Sans `register_jobs()`, les jobs n'apparaissent pas dans l'UI Nautobot même s'ils sont importables.

### Exemple Complet `__init__.py`

```python
"""Nautobot Route Tracking Plugin."""

from importlib.metadata import metadata

from nautobot.apps import NautobotAppConfig

__version__ = metadata("nautobot-route-tracking")["Version"]


class NautobotRouteTrackingConfig(NautobotAppConfig):
    """Nautobot App Config for Route Tracking.

    See: https://docs.nautobot.com/projects/core/en/stable/development/apps/api/nautobot-app-config/
    """

    name = "nautobot_route_tracking"
    verbose_name = "Route Tracking"
    version = __version__
    author = "Thomas"
    author_email = "thomas@networktocode.com"
    description = "Track IP routing tables from network devices"
    base_url = "route-tracking"              # kebab-case, pas snake_case
    required_settings = []                   # Ex: ["NAUTOBOT_ROUTE_TRACKING_SECRET"]
    min_version = "3.0.6"
    max_version = "3.99"
    default_settings = {
        "retention_days": 90,
        "purge_enabled": True,
        "nornir_workers": 50,
        "device_timeout": 30,
    }

    def ready(self) -> None:
        """Hook appelé quand l'app Django est prête."""
        super().ready()
        from nautobot_route_tracking.signals import register_signals
        register_signals(sender=self.__class__)
        self._fix_job_grouping()

    @staticmethod
    def _fix_job_grouping() -> None:
        """Corrige le grouping des jobs à chaque démarrage."""
        from django.db import OperationalError, ProgrammingError
        try:
            from nautobot.extras.models import Job
            Job.objects.filter(
                module_name__startswith="nautobot_route_tracking.jobs"
            ).update(grouping="Route Tracking")
        except (OperationalError, ProgrammingError):
            pass


config = NautobotRouteTrackingConfig  # Variable obligatoire — Nautobot la cherche
```

**Point critique** : La variable `config` en bas de fichier est **obligatoire**. Nautobot l'importe automatiquement pour enregistrer le plugin.

---

## 3. `pyproject.toml`

### Section `[tool.poetry]` Complète

```toml
[tool.poetry]
name = "nautobot-route-tracking"            # kebab-case — nom PyPI
version = "1.0.0"                           # semver
description = "Nautobot plugin for tracking IP routing tables from network devices"
authors = ["Thomas <thomas@networktocode.com>"]
license = "Apache-2.0"
readme = "README.md"
homepage = "https://github.com/networktocode/nautobot-route-tracking"
repository = "https://github.com/networktocode/nautobot-route-tracking"
documentation = "https://docs.nautobot.com/projects/route-tracking/"
keywords = ["nautobot", "nautobot-plugin", "routing", "bgp", "network-automation"]
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
    "Topic :: System :: Networking",
]
packages = [{ include = "nautobot_route_tracking" }]  # snake_case — répertoire source
```

### Dépendances Obligatoires

```toml
[tool.poetry.dependencies]
python = ">=3.10,<3.14"
nautobot = "^3.0.6"                         # Framework de base
nornir = "^3.4.0"                           # Orchestration parallèle
nornir-nautobot = "^4.0.0"                  # Intégration Nornir/Nautobot ORM
nautobot-plugin-nornir = "^3.0.0"           # Inventory ORM + Credentials
nornir-napalm = "^0.5.0"                    # Driver NAPALM pour Nornir
nornir-netmiko = "^1.0.0"                   # Driver Netmiko pour Nornir
napalm = "^5.0.0"                           # Abstraction multi-vendor
netmiko = "^4.3.0"                          # SSH multi-vendor
```

### Dev Dependencies

```toml
[tool.poetry.group.dev.dependencies]
pytest = "^8.0.0"
pytest-cov = "^4.1.0"
pytest-django = "^4.8.0"
factory-boy = "^3.3.0"                      # Génération de données de test
coverage = "^7.4.0"
ruff = "^0.2.0"                             # Linter + formateur (remplace black + flake8)
pylint = "^3.0.0"
pylint-django = "^2.5.0"
pre-commit = "^3.6.0"
```

### `[build-system]`

```toml
[build-system]
requires = ["poetry-core>=1.0.0"]
build-backend = "poetry.core.masonry.api"
```

**Note** : Il n'y a pas d'entry point explicite à déclarer pour les plugins Nautobot. Nautobot détecte les plugins via `PLUGINS` dans `nautobot_config.py`, pas via `entry_points`. Le mécanisme de découverte est purement basé sur la configuration.

---

## 4. Configuration Pytest pour Nautobot

### Section `[tool.pytest.ini_options]`

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
addopts = "-v --tb=short"
DJANGO_SETTINGS_MODULE = "tests.test_settings"
```

### `tests/test_settings.py`

Ce fichier est **critique** et contient plusieurs pièges spécifiques à Nautobot 3.x :

```python
"""Django settings pour les tests du plugin nautobot_route_tracking."""

from nautobot.core.settings import *  # noqa: F401, F403 — importer les settings Nautobot de base
from nautobot.core.settings_funcs import parse_redis_connection

# Clé secrète pour les tests (ne pas utiliser en production)
SECRET_KEY = "test-secret-key-for-testing-only-not-for-production"

# Base de données en mémoire pour les tests
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Pas de Redis pour les tests
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# CRITIQUE : Les deux sont nécessaires
# PLUGINS : utilisé par nautobot-server (CI migrations)
# INSTALLED_APPS.append() : requis par pytest-django (django.setup() ne traite pas PLUGINS)
PLUGINS = ["nautobot_route_tracking"]
INSTALLED_APPS.append("nautobot_route_tracking")  # noqa: F405

# Configuration du plugin pour les tests
PLUGINS_CONFIG = {
    "nautobot_route_tracking": {
        "retention_days": 30,
        "purge_enabled": False,
        "nornir_workers": 2,
        "device_timeout": 5,
    }
}
```

**Pièges critiques** :

1. `PLUGINS` seul ne suffit pas avec pytest-django — ajouter aussi dans `INSTALLED_APPS`
2. `INSTALLED_APPS` est une liste définie dans les settings Nautobot de base importés par `*`
3. En CI, utiliser `nautobot-server makemigrations` (pas `django-admin`) car `nautobot-server` traite `PLUGINS`

### Commande CI pour les Migrations

```yaml
# ✅ Correct : nautobot-server traite PLUGINS
- name: Run migrations
  run: |
    poetry run nautobot-server init
    echo 'PLUGINS = ["nautobot_route_tracking"]' >> ~/.nautobot/nautobot_config.py
    poetry run nautobot-server makemigrations nautobot_route_tracking
    poetry run nautobot-server migrate

# ❌ Incorrect : django-admin ne traite pas PLUGINS
- name: Run migrations
  env:
    DJANGO_SETTINGS_MODULE: tests.test_settings
  run: poetry run django-admin makemigrations nautobot_route_tracking
```

---

## 5. Configuration Ruff

### Section `[tool.ruff]`

```toml
[tool.ruff]
line-length = 120
target-version = "py310"
extend-exclude = ["migrations"]             # Ne pas linter les migrations auto-générées

[tool.ruff.lint]
select = [
    "E",     # pycodestyle errors
    "W",     # pycodestyle warnings
    "F",     # Pyflakes
    "I",     # isort (tri des imports)
    "N",     # pep8-naming
    "D",     # pydocstring
    "UP",    # pyupgrade (modernisation syntax Python)
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
    "D203",   # 1 blank line required before class docstring (conflit avec D211)
    "D213",   # Multi-line summary at second line (conflit avec D212)
    "D401",   # Imperative mood (trop strict)
    "D406",   # Section name should end with newline
    "D407",   # Missing dashed underline after section
    "D413",   # Missing blank line after last section
    "RUF012", # Mutable class attributes (standard Django Meta/admin patterns)
    "SIM102", # Nested if statements (parfois plus lisible)
]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["D", "S101"]                  # Pas de docstrings requises + assert OK dans tests
"**/migrations/*" = ["D", "E501", "I"]    # Migrations auto-générées : ignorer tout

[tool.ruff.lint.isort]
known-first-party = ["nautobot_route_tracking"]
known-third-party = ["nautobot"]
```

### `.gitignore` Patterns Importants

```gitignore
# Python
__pycache__/
*.py[codz]
*.egg-info/
dist/
build/
.eggs/

# Tests
htmlcov/
.coverage
.coverage.*
.pytest_cache/
coverage.xml

# Django
*.log
local_settings.py
db.sqlite3

# Environments
.env
.envrc
.venv
venv/

# Poetry
# poetry.lock — généralement commité pour reproducibilité
# poetry.toml

# Celery
celerybeat-schedule
celerybeat.pid

# Tools
.ruff_cache/
.mypy_cache/
.tox/
/site                  # mkdocs build

# Éditeurs
.idea/
.vscode/
```

---

## 6. Enregistrement de l'API REST

### `api/__init__.py`

Fichier vide obligatoire pour que Python reconnaisse le répertoire comme package :

```python
# nautobot_route_tracking/api/__init__.py
```

### `api/urls.py`

```python
"""API URL configuration pour le plugin nautobot_route_tracking."""

from nautobot.apps.api import OrderedDefaultRouter

from nautobot_route_tracking.api.views import (
    RouteEntryViewSet,
    RoutingTableViewSet,
)

router = OrderedDefaultRouter()
router.register("route-entries", RouteEntryViewSet)
router.register("routing-tables", RoutingTableViewSet)

urlpatterns = router.urls
```

**Points clés** :

- Utiliser `OrderedDefaultRouter` de `nautobot.apps.api` (pas `DefaultRouter` de DRF)
- Les slugs des routes sont en **kebab-case** (ex: `"route-entries"`)
- Nautobot monte automatiquement ces URLs sous `/api/plugins/<base_url>/`

### `api/views.py`

```python
from nautobot.apps.api import NautobotModelViewSet

from nautobot_route_tracking.api.serializers import RouteEntrySerializer
from nautobot_route_tracking.filters import RouteEntryFilterSet
from nautobot_route_tracking.models import RouteEntry


class RouteEntryViewSet(NautobotModelViewSet):
    """API ViewSet pour RouteEntry."""

    queryset = RouteEntry.objects.select_related(
        "device",
        "device__location",
        "interface",
    ).prefetch_related("tags")
    serializer_class = RouteEntrySerializer
    filterset_class = RouteEntryFilterSet
```

### `api/serializers.py`

```python
from nautobot.apps.api import NautobotModelSerializer

from nautobot_route_tracking.models import RouteEntry


class RouteEntrySerializer(NautobotModelSerializer):
    """Serializer pour RouteEntry."""

    class Meta:
        model = RouteEntry
        fields = [
            "id",
            "url",
            "display",
            "device",
            "prefix",
            "next_hop",
            "protocol",
            "first_seen",
            "last_seen",
            "tags",
            "created",
            "last_updated",
        ]
        read_only_fields = ["first_seen", "created", "last_updated"]
```

### `urls.py` (UI)

```python
"""URL configuration UI pour le plugin nautobot_route_tracking."""

from django.urls import path
from nautobot.apps.urls import NautobotUIViewSetRouter

from nautobot_route_tracking.views import (
    RouteEntryUIViewSet,
    RoutingDashboardView,
)

app_name = "nautobot_route_tracking"

router = NautobotUIViewSetRouter()
router.register("route-entries", RouteEntryUIViewSet)

urlpatterns = [
    path("dashboard/", RoutingDashboardView.as_view(), name="dashboard"),
]

urlpatterns += router.urls
```

**Points clés** :

- `app_name` est obligatoire pour le namespace des URLs (`plugins:nautobot_route_tracking:...`)
- Utiliser `NautobotUIViewSetRouter` de `nautobot.apps.urls`
- Nautobot monte les UI URLs sous `/plugins/<base_url>/`

---

## 7. Navigation

```python
# nautobot_route_tracking/navigation.py
from nautobot.apps.ui import (
    NavMenuAddButton,
    NavMenuGroup,
    NavMenuItem,
    NavMenuTab,
)

menu_items = (
    NavMenuTab(
        name="Route Tracking",
        weight=500,
        groups=(
            NavMenuGroup(
                name="Routes",
                weight=50,
                items=(
                    NavMenuItem(
                        link="plugins:nautobot_route_tracking:routeentry_list",
                        name="Route Entries",
                        permissions=["nautobot_route_tracking.view_routeentry"],
                        buttons=(
                            NavMenuAddButton(
                                link="plugins:nautobot_route_tracking:routeentry_add",
                                permissions=["nautobot_route_tracking.add_routeentry"],
                            ),
                        ),
                        weight=100,
                    ),
                ),
            ),
        ),
    ),
)
```

**Pattern de nommage des links** : `"plugins:<app_name>:<model_lower>_list"` et `"plugins:<app_name>:<model_lower>_add"` (générés automatiquement par `NautobotUIViewSetRouter`).

---

## 8. Coverage

### Section `[tool.coverage.run]`

```toml
[tool.coverage.run]
source = ["nautobot_route_tracking"]
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
fail_under = 80                             # Standard NTC : 80% minimum
```

---

## 9. Différences Nautobot 3.x vs 2.x

### Tableau des Imports

| Composant | Nautobot 2.x | Nautobot 3.x |
| --------- | ------------ | ------------ |
| App Config | `from nautobot.extras.plugins import PluginConfig` | `from nautobot.apps import NautobotAppConfig` |
| Modèles de base | `from nautobot.core.models.generics import PrimaryModel` | `from nautobot.apps.models import PrimaryModel` |
| FilterSets | `from nautobot.extras.filters import NautobotFilterSet` | `from nautobot.apps.filters import NautobotFilterSet` |
| Filtres helpers | `from nautobot.utilities.filters import NaturalKeyOrPKMultipleChoiceFilter` | `from nautobot.apps.filters import NaturalKeyOrPKMultipleChoiceFilter` |
| Serializers | `from nautobot.extras.api.serializers import NautobotModelSerializer` | `from nautobot.apps.api import NautobotModelSerializer` |
| API ViewSets | `from nautobot.core.api.views import NautobotModelViewSet` | `from nautobot.apps.api import NautobotModelViewSet` |
| API Router | `from rest_framework.routers import DefaultRouter` | `from nautobot.apps.api import OrderedDefaultRouter` |
| UI ViewSets | `from nautobot.core.views.generic import ObjectListView` (custom) | `from nautobot.apps.views import NautobotUIViewSet` |
| UI Router | (manuel) | `from nautobot.apps.urls import NautobotUIViewSetRouter` |
| Tables | `from nautobot.core.tables import BaseTable, ButtonsColumn` | `from nautobot.apps.tables import BaseTable, ButtonsColumn, ToggleColumn` |
| Navigation | `from nautobot.extras.plugins import PluginMenuItem` | `from nautobot.apps.ui import NavMenuTab, NavMenuGroup, NavMenuItem` |
| TemplateExtension | `from nautobot.extras.plugins import PluginTemplateExtension` | `from nautobot.apps.ui import TemplateExtension` |
| Jobs (classes) | `from nautobot.extras.jobs import Job, ObjectVar` | `from nautobot.apps.jobs import Job, ObjectVar, BooleanVar` |
| Jobs (register) | Non requis (auto) | `from nautobot.core.celery import register_jobs` |
| Forms | `from nautobot.utilities.forms import BootstrapMixin` | `from nautobot.apps.forms import NautobotModelForm` |
| Pagination | `from nautobot.core.paginator import EnhancedPaginator` | `from nautobot.core.views.paginator import EnhancedPaginator, get_paginate_count` |
| SearchFilter | N/A | `from nautobot.apps.filters import SearchFilter` |

### Changements Majeurs en 3.x

**1. `register_jobs()` est obligatoire**

En Nautobot 3.x, les jobs ne sont **plus** auto-enregistrés. `register_jobs(*jobs)` doit être appelé explicitement dans `jobs/__init__.py`.

**2. `NautobotUIViewSet` remplace les vues génériques**

En 3.x, au lieu de composer manuellement `ObjectListView`, `ObjectEditView`, etc., on hérite de `NautobotUIViewSet` qui gère automatiquement list/detail/add/edit/delete/bulk_destroy/bulk_edit.

**3. Suppression des `NestedSerializer`**

En 3.x, les classes `NestedXxxSerializer` sont supprimées. Les relations FK dans l'API utilisent directement le serializer de base avec `?depth=N`.

**4. Suppression de `CSVForm` et `to_csv`**

L'export CSV passe désormais par l'API REST (pas de forms dédiés).

**5. FilterSet : champs FK multi-valeurs par défaut**

En 3.x, les filtres sur FK génèrent automatiquement des `MultipleChoiceFilter`. Pour les tests, passer les valeurs FK en **liste** :

```python
# ✅ Correct Nautobot 3.x
filterset = RouteEntryFilterSet({"device": [str(device.pk)]})

# ❌ Incorrect (2.x style)
filterset = RouteEntryFilterSet({"device": device.pk})
```

**6. Template rendering standard obligatoire**

```django
{# ✅ Template Nautobot standard #}
{% render_table table "inc/table.html" %}
{% include 'inc/paginator.html' with paginator=table.paginator page=table.page %}

{# ❌ Template django-tables2 générique #}
{% render_table table "django_tables2/bootstrap5.html" %}
```

**7. `ScriptVariable` : attributs dans `field_attrs`**

```python
# ✅ Nautobot 3.x
assert job.retention_days.field_attrs["initial"] == 90

# ❌ Nautobot 2.x style
assert job.retention_days.default == 90
```

**8. `NautobotAppConfig` remplace `PluginConfig`**

```python
# ✅ Nautobot 3.x
from nautobot.apps import NautobotAppConfig

class MyConfig(NautobotAppConfig):
    pass

# ❌ Nautobot 1.x/2.x
from nautobot.extras.plugins import PluginConfig

class MyConfig(PluginConfig):
    pass
```

---

## 10. Récapitulatif : Structure de `nautobot_netdb_tracking` comme Référence

Le plugin `nautobot_netdb_tracking` est la référence principale éprouvée en production. Voici sa structure complète :

```
nautobot_netdb_tracking/                   # Repo git
├── .gitignore
├── .ruff_cache/
├── LICENSE
├── pyproject.toml
├── docs/
│   ├── cable_autocreate_guide.md
│   ├── job_topology.md
│   └── platform_configuration.md
│
├── nautobot_netdb_tracking/               # Package Python
│   ├── __init__.py                        # NautobotNetDBTrackingConfig
│   ├── models.py                          # MACAddressHistory, ARPEntry, TopologyConnection
│   ├── filters.py                         # NautobotFilterSet pour chaque modèle
│   ├── forms.py                           # UI Forms + Filter Forms
│   ├── tables.py                          # BaseTable pour chaque modèle
│   ├── views.py                           # NautobotUIViewSet + vues custom
│   ├── urls.py                            # UI routing (NautobotUIViewSetRouter + path())
│   ├── navigation.py                      # NavMenuTab/Group/Item
│   ├── signals.py                         # post_migrate : enable jobs + fix grouping
│   ├── template_content.py                # TemplateExtension : tabs Device + Interface
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── serializers.py                 # NautobotModelSerializer
│   │   ├── views.py                       # NautobotModelViewSet
│   │   └── urls.py                        # OrderedDefaultRouter
│   │
│   ├── jobs/
│   │   ├── __init__.py                    # register_jobs()
│   │   ├── _base.py                       # BaseCollectionJob (classe abstraite)
│   │   ├── collect_mac_arp.py
│   │   ├── collect_topology.py
│   │   └── purge_old_data.py
│   │
│   ├── migrations/
│   │   ├── __init__.py
│   │   ├── 0001_initial.py
│   │   ├── 0002_rename_constraints.py
│   │   └── 0003_add_first_seen_indexes.py
│   │
│   ├── static/
│   │   └── nautobot_netdb_tracking/
│   │       ├── css/netdb.css
│   │       └── js/netdb.js
│   │
│   └── templates/
│       └── nautobot_netdb_tracking/
│           └── inc/
│               └── interface_netdb_panel.html
│
└── tests/
    └── __init__.py
```

### Patterns Clés Observés dans `nautobot_netdb_tracking`

**`__init__.py`** :

- `__version__` lu depuis les metadata du package installé (`importlib.metadata`)
- `ready()` appelle `super().ready()` puis les signals puis `_fix_job_grouping()`
- `_fix_job_grouping()` est `@staticmethod` avec try/except `(OperationalError, ProgrammingError)`
- `config = NautobotNetDBTrackingConfig` en dernière ligne (obligatoire)

**`api/urls.py`** :

- `OrderedDefaultRouter` depuis `nautobot.apps.api`
- Slugs en kebab-case : `"mac-address-history"`, `"arp-entries"`, `"topology-connections"`

**`urls.py` (UI)** :

- `NautobotUIViewSetRouter` depuis `nautobot.apps.urls`
- `app_name = "nautobot_netdb_tracking"` pour le namespace
- Vues custom montées avec `path()` (dashboard, lookup, tabs spécifiques)
- `urlpatterns += router.urls` à la fin

**`jobs/__init__.py`** :

- Import de `register_jobs` depuis `nautobot.core.celery`
- Liste `jobs = [...]` puis `register_jobs(*jobs)`

**`signals.py`** :

- `post_migrate.connect(handler, sender=sender)` avec `sender=self.__class__` (AppConfig)
- Scoper sur l'AppConfig évite de re-déclencher pour les migrations d'autres apps
- Fonctions utilitaires (`get_retention_days`, `is_purge_enabled`) lisent `settings.PLUGINS_CONFIG`

**`navigation.py`** :

- `NavMenuTab` > `NavMenuGroup` > `NavMenuItem`
- Links format : `"plugins:nautobot_netdb_tracking:dashboard"`, `"plugins:nautobot_netdb_tracking:topologyconnection_list"`
- `NavMenuAddButton` pour le bouton "+" sur les listes

**`template_content.py`** :

- `TemplateExtension` depuis `nautobot.apps.ui`
- `model = "dcim.device"` (format `app_label.ModelName`)
- `detail_tabs()` retourne liste de dicts avec `"title"` et `"url"`
- `right_page()` retourne `self.render("template.html", extra_context={...})`
- Variable globale `template_extensions = [...]` exposée dans le module

---

## Sources

- [GitHub - nautobot/cookiecutter-nautobot-app](https://github.com/nautobot/cookiecutter-nautobot-app)
- [NautobotAppConfig Reference](https://docs.nautobot.com/projects/core/en/stable/development/apps/api/nautobot-app-config/)
- [App Setup Documentation](https://docs.nautobot.com/projects/core/en/stable/development/apps/api/setup/)
- [Code Updates (Migration Guide)](https://docs.nautobot.com/projects/core/en/stable/development/apps/migration/code-updates/)
- [Migrating v2 to v3](https://docs.nautobot.com/projects/core/en/stable/development/apps/migration/from-v2/migrating-v2-to-v3/)
- [Cookiecutter Quick Start](https://docs.nautobot.com/projects/cookiecutter-nautobot-app/en/latest/user/quick-start/)
- [Version 3.0 Release Notes](https://docs.nautobot.com/projects/core/en/stable/release-notes/version-3.0/)
