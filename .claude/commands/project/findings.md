---
name: findings
description: "Manage audit findings registry — show, add, resolve, stats, sync"
arguments: $1
---

# /project:findings — Findings Registry Manager

## Input

Action: `$1` (one of: `show`, `add`, `resolve`, `stats`, `sync`)

## Registry Location

`reports/findings/registry.yml`

## Actions

### show (default)

```bash
python3 scripts/findings.py show
python3 scripts/findings.py show --severity HIGH
python3 scripts/findings.py show --all
```

### add

```bash
python3 scripts/findings.py add --severity HIGH --title "Issue title" --file "nautobot_route_tracking/x.py:42" --category testing --description "Details"
```

### resolve

```bash
python3 scripts/findings.py resolve F-001 --reason "Fixed in commit abc123"
```

### stats

```bash
python3 scripts/findings.py stats
```

### sync

Parse audit reports and add new findings to registry:

```bash
python3 scripts/findings.py sync
```
