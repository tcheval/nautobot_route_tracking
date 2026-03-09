# CLAUDE.md — Project Configuration

> This file is the primary instruction set for Claude Code in this project.
> **Version:** 3.0

---

## Project Context

**Project:** nautobot-route-tracking
**Owner:** tcheval
**Stack:** Python 3.10+, Nautobot 3.0.6, Django 4.2+, Nornir, NAPALM, PostgreSQL 15, Redis 7
**Architecture:** Nautobot plugin with Nornir/NAPALM collection, NetDB UPDATE/INSERT logic

---

## Convention Loading Instructions

**Load conventions based on task context — always start with core:**

| Context | Load sequence |
| ------- | ------------- |
| General work | `_convention/_core.md` |
| Plugin development | `_convention/_core.md` → `_convention/_nautobot-plugin.md` |
| Review / Debug | `_convention/_core.md` → `_convention/_nautobot-plugin.md` |

**Convention hierarchy:**

- `_core.md` principles are **immutable** — they apply to ALL domains
- Domain files extend core with implementation specifics
- Conflicts → `_core.md` wins unconditionally
- See `_convention/README.md` for governance rules

---

## Code Review

For Nautobot 3.x application review, follow the instructions in `AGENTS.md`.

---

## Essential Reading

**Before writing any code**, read **[docs/nautobot_plugin_dev_lessons.md](docs/nautobot_plugin_dev_lessons.md)** — a guide of hard-won lessons covering Nornir parallelism, NautobotORMInventory quirks, Nautobot 3.x pitfalls, and testing patterns.

For specifications, see **[docs/SPECIFICATIONS.md](docs/SPECIFICATIONS.md)** — the authoritative data model, collection strategy, and feature scope.

---

## Hard Rules

These rules are non-negotiable. Violation = immediate fix required.

- **NEVER** use `.save()` — always `validated_save()`
- **NEVER** use `napalm_get` — always `napalm_cli` with platform-specific parsing
- **NEVER** import `napalm` directly — always go through Nornir
- **NEVER** hardcode credentials — use SecretsGroup via `CredentialsNautobotSecrets`
- **NEVER** use `print()` for logging — use `self.logger`
- **NEVER** loop sequentially over devices — use single `nr.run()` with parallel workers
- **NEVER** degrade production code for test infrastructure
- **ALWAYS** register jobs via `register_jobs()` in `jobs/__init__.py`
- **ALWAYS** inherit collection jobs from `BaseCollectionJob`
- **ALWAYS** define Nornir tasks at module level (not inside classes)
- **ALWAYS** run validation before committing (`/project:validate`)

---

## Formatting Standards

### Code Style

- **Indent:** 4 spaces (Python), 2 spaces (YAML)
- **Line length:** 120 characters max
- **Quotes:** Double quotes for Python strings
- **Trailing commas:** Always (enables clean diffs)
- **Linter:** ruff (`ruff check`, `ruff format`)
- **Type hints:** Python 3.10+ throughout

### Markdown

- Tables: `| value |` (spaces around pipes)
- Code blocks: always specify language tag
- **Language: English only** — all `.md` files must be in English

### Comments

- **Language: English only** — all code comments must be in English
- Comments explain **why**, never **what**
- No commented-out code in committed files

---

## Project Overview

**nautobot-route-tracking** is a Nautobot plugin that collects and historizes routing table entries from network devices via NAPALM CLI commands (`napalm_cli`). It follows the same UPDATE/INSERT logic as [nautobot-netdb-tracking](https://github.com/tcheval/nautobot-netdb-tracking), tracking route changes over time with full history.

### Key Objectives

1. **Historical Tracking**: Maintain 90-day history of route entries with intelligent UPDATE vs INSERT logic
2. **Enterprise Scale**: Handle large device fleets with parallel collection (Nornir)
3. **Multi-vendor Support**: Cisco IOS/IOS-XE, Arista EOS (NAPALM drivers)
4. **ECMP Support**: Each next-hop is a separate `RouteEntry` row (UniqueConstraint includes `next_hop`)
5. **Nautobot Integration**: Native UI, API, permissions, Device tab, and data models

---

## Project Structure

```text
nautobot_route_tracking/        # Plugin source code
├── __init__.py                 # NautobotAppConfig
├── models.py                   # RouteEntry + EXCLUDED_ROUTE_NETWORKS + normalize helpers
├── constants.py                # SUPPORTED_PLATFORMS
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
│   ├── serializers.py          # RouteEntrySerializer
│   ├── views.py                # RouteEntryViewSet
│   └── urls.py                 # OrderedDefaultRouter
├── jobs/
│   ├── __init__.py             # register_jobs(CollectRoutesJob, PurgeOldRoutesJob)
│   ├── _base.py                # BaseCollectionJob + utilities
│   ├── collect_routes.py       # CollectRoutesJob
│   └── purge_old_routes.py     # PurgeOldRoutesJob
├── graphql/
│   └── types.py                # RouteEntryType
└── templates/nautobot_route_tracking/
    ├── device_route_tab.html
    └── inc/
        └── device_route_panel.html

tests/                          # Unit and integration tests
scripts/
├── metrics.py                  # Project health metrics (--json, --save, --compare)
├── findings.py                 # Findings registry manager (show, add, resolve, stats, sync)
└── fixdoc.py                   # Markdown lint, fix, and language check

reports/
├── audit/                      # Audit reports (audit_YYYYMMDD.md)
├── findings/
│   └── registry.yml            # Findings registry (single source of truth)
└── metrics/                    # Metrics snapshots (snapshot_YYYYMMDD_HHMM.json)

_convention/
├── _core.md                    # Universal principles (immutable)
├── _nautobot-plugin.md         # Nautobot plugin domain rules
├── _domain-template.md         # Template for new domain conventions
└── README.md                   # Convention governance

.claude/
├── agents/                     # Specialized review agents
├── commands/project/           # Slash commands (/project:validate, /project:commit, etc.)
└── settings.local.json         # Local permissions

docs/
├── SPECIFICATIONS.md           # Authoritative data model and feature scope
├── nautobot_plugin_dev_lessons.md  # Hard-won development lessons
├── development.md              # Development guide
├── installation.md             # Installation guide
└── usage.md                    # Usage guide
```

---

## Commands

### /project:validate

Run lint and test checks. Use before committing.

```bash
/project:validate                    # Full validation (ruff + pytest in Docker)
/project:validate nautobot_route_tracking/  # Scope to path
```

### /project:commit

Stage and commit with conventional commit format. Runs validate first.

```bash
/project:commit                      # Auto-detect type from changes
/project:commit fix                  # Force commit type
/project:commit push release         # Commit + push + GitHub release with wheel
```

### /project:audit

Deep project audit — checks convention compliance, code quality, structural integrity. Saves report to `reports/audit/` and syncs findings.

### /project:review

Follow up on audit findings. Cross-references findings registry and tracks remediation.

### /project:metrics

Display project health metrics — files, tests, findings, compliance.

```bash
/project:metrics                     # Display metrics
/project:metrics --save              # Save snapshot
/project:metrics --compare           # Compare with latest snapshot
```

### /project:findings

Manage audit findings registry.

```bash
/project:findings show               # Show open findings
/project:findings add                # Add a new finding
/project:findings resolve            # Resolve a finding
/project:findings stats              # Summary statistics
```

### /project:fixdoc

Fix markdown formatting and check language compliance.

### /project:status

Single-screen project dashboard — version, quality, findings, compliance, git status.

---

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

### NetDB Logic (CRITICAL)

The core differentiator from simple polling is the **UPDATE vs INSERT** logic:

```python
@classmethod
def update_or_create_entry(cls, device, network, protocol, vrf=None, next_hop="", **kwargs):
    with transaction.atomic():
        existing = cls.objects.select_for_update().filter(
            device=device, vrf=vrf, network=network,
            next_hop=next_hop, protocol=protocol,
        ).first()
        if existing:
            existing.last_seen = timezone.now()
            for field, value in kwargs.items():
                setattr(existing, field, value)
            existing.validated_save()
            return existing, False
        entry = cls(
            device=device, vrf=vrf, network=network,
            next_hop=next_hop, protocol=protocol,
            last_seen=timezone.now(), **kwargs
        )
        entry.validated_save()
        return entry, True
```

**Result**: History only contains actual changes, not redundant snapshots. ECMP routes (same prefix, different next-hops) are separate rows.

---

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
    network           = CharField(max_length=50)
    prefix_length     = PositiveSmallIntegerField()
    protocol          = CharField(max_length=20, choices=Protocol.choices)
    next_hop          = CharField(max_length=50, blank=True, default="")
    outgoing_interface = ForeignKey("dcim.Interface", SET_NULL, null=True, blank=True)
    metric            = PositiveIntegerField(default=0)
    admin_distance    = PositiveSmallIntegerField(default=0)
    is_active         = BooleanField(default=True)
    routing_table     = CharField(max_length=100, default="default")
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
- Protocol normalized to **lowercase** before storage

---

## NAPALM CLI Collection

Collection uses `napalm_cli` with platform-specific commands (not `napalm_get`/`get_route_to()`):

- **Arista EOS**: `show ip route | json` → structured JSON, parsed by `_parse_eos_routes()`
- **Cisco IOS**: `show ip route` → text output, parsed via TextFSM (`ntc-templates`)

**Excluded prefixes** (defined in `models.py`): multicast (`224.0.0.0/4`), link-local (`169.254.0.0/16`, `fe80::/10`), loopback (`127.0.0.0/8`, `::1/128`).

---

## Nornir / NAPALM Convention (MANDATORY)

This project uses **exclusively** Nornir + nornir_napalm for network access. All SSoT (credentials, drivers, optional_args) resolved via Nautobot.

### Required Patterns

- All collection jobs MUST inherit from `BaseCollectionJob` (`jobs/_base.py`)
- Nornir init via `BaseCollectionJob.initialize_nornir()`
- Tasks use `napalm_cli` only (not `napalm_get`)
- Single `nr.run()` call for parallel execution
- Error handling via `_extract_nornir_error()` for `NornirSubTaskError`
- Queryset filter on `platform__network_driver__in=SUPPORTED_PLATFORMS`
- Nornir tasks defined at module level (not inside classes)
- Logging via `self.logger`, never `print()` or `logging.getLogger()`

### Forbidden in Jobs

- `import napalm` or `from napalm import ...`
- `device.get_napalm_device()`
- `napalm_get` (use `napalm_cli` + platform-specific parsing)
- `SimpleInventory` or manual Nornir inventory
- Manual credentials (`nr.inventory.defaults.username = ...`)
- `subprocess.run(["napalm", ...])`
- Sequential device loops
- `print()` for logging

---

## Critical Pitfalls

### `register_jobs` — MANDATORY in `jobs/__init__.py`

Without `register_jobs()` at module level, jobs don't appear in Nautobot UI.

### NornirSubTaskError — `result` is a `MultiResult` (list)

```python
# BAD — exc.result.exception doesn't exist (it's a list)
# GOOD — iterate the MultiResult via _extract_nornir_error()
```

### NaturalKeyOrPKMultipleChoiceFilter — input LIST required

```python
filterset = RouteEntryFilterSet({"device": [str(device.pk)]})  # list, not bare string
```

### Templates — always `inc/table.html`

```django
{% render_table table "inc/table.html" %}
```

### Paginator — `EnhancedPaginator` required

```python
from nautobot.core.views.paginator import EnhancedPaginator, get_paginate_count
```

### Tab templates — extend `generic/object_detail.html`

### `{% load %}` on separate lines — Django misparses combined `from` lines

### RuntimeError — only if zero successes

```python
if self.stats["devices_success"] == 0 and self.stats["devices_failed"] > 0:
    raise RuntimeError(msg)
```

---

## Testing Standards

- **No local venv** — all tests run inside `nautobot` Docker container
- `validated_save()` always in fixtures — never `.create()` or `.save()`
- Filter tests use LIST format for FK fields
- Job tests mock `napalm_cli` network calls
- Factory Boy for test data generation

---

## Development Workflow

### Lint

```bash
python3 -m ruff check nautobot_route_tracking/ tests/
python3 -m ruff format --check nautobot_route_tracking/ tests/
```

### Tests (in Docker)

```bash
docker cp ./tests nautobot:/tmp/tests
docker exec nautobot bash -c "cd /tmp && python -m pytest tests/ -v --tb=short"
```

### Hot Deploy (development)

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

### Release

Build wheel + sdist, upload to GitHub Release as assets.

```bash
python3 -m build --wheel --sdist
gh release upload v<version> dist/*.whl dist/*.tar.gz
```

---

## When Uncertain

| Situation | Action |
| --------- | ------ |
| Where to place a file | Choose the highest appropriate level in the hierarchy |
| Flat vs nested structure | Prefer flat — nest only when > 7 items at one level |
| Missing information | **Ask** — never guess or use silent defaults |
| Convention conflict | `_core.md` wins. Always. |
| Not sure if needed | Don't add it (YAGNI — `_core.md` §1.2) |

**Reference:** `_convention/_core.md` for all universal principles, `_convention/_nautobot-plugin.md` for Nautobot-specific rules.
