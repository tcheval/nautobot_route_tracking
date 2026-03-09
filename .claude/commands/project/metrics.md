---
name: metrics
description: "Display project health metrics — files, tests, findings, compliance"
arguments: $1
---

# /project:metrics — Project Health Metrics

## Input

Action: `$1` (optional: `display` (default), `--save`, `--compare`, `--json`)

## Steps

### display (default)

```bash
python3 scripts/metrics.py
```

### --save

```bash
python3 scripts/metrics.py --save
```

### --compare

```bash
python3 scripts/metrics.py --compare $(ls -t reports/metrics/snapshot_*.json | head -1)
```

### --json

```bash
python3 scripts/metrics.py --json
```

## Quick Reference

| Metric | Source |
| --- | --- |
| Source files | `nautobot_route_tracking/**/*.py` |
| Tests | `tests/**/*.py` — files + `test_*` functions |
| Findings | `reports/findings/registry.yml` |
| Conventions | `_convention/*.md` |
| Agents | `.claude/agents/*.md` |
| Commands | `.claude/commands/**/*.md` |
| Compliance | 4 auto checks (README Guard, English-only, no `.save()`, `register_jobs`) |
