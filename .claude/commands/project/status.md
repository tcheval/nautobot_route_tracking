---
name: status
description: "Single-screen project status dashboard"
---

# /project:status — Project Dashboard

## Purpose

Display a single-screen view of the project's current state: version, quality, findings, compliance, and git status.

## Execution

### Step 1: Gather Data (parallel)

Run all of the following in parallel:

1. **Version** — Read `CHANGELOG.md` and extract the latest `## [x.y.z]` version tag

2. **Git info** — Run:

```bash
git log --oneline -5
git status --short
git rev-parse --abbrev-ref HEAD
```

3. **Metrics** — Run:

```bash
python3 scripts/metrics.py --json
```

4. **Open findings** — Read `reports/findings/registry.yml` and count findings where `status: open`, grouped by severity.

### Step 2: Format Output

Present the data using this format:

```markdown
# Project Status

| Field | Value |
| --- | --- |
| Version | x.y.z |
| Branch | main |
| Last commit | `abc1234` type(scope): description |

## Code

| Metric | Value |
| --- | --- |
| Source files | N |
| Test files | N |
| Test functions | N |

## Findings

| Severity | Open | Resolved |
| --- | --- | --- |
| CRITICAL | N | N |
| HIGH | N | N |
| WARNING | N | N |
| INFO | N | N |
| **Total** | **N** | **N** |

Resolution rate: N%

## Compliance (N/4)

| Check | Status |
| --- | --- |
| No `.save()` | PASS/FAIL |
| No `napalm_get` | PASS/FAIL |
| `register_jobs()` present | PASS/FAIL |
| English-only docs | PASS/FAIL |

## Git Status

<output of git status --short, or "Clean working tree">

### Recent Commits

<last 5 commits from git log --oneline>
```

### Step 3: Health Indicator

At the top of the output, add a health indicator:

- **GREEN** — 0 CRITICAL findings, compliance >= 3/4
- **YELLOW** — 1-2 CRITICAL findings OR compliance 2/4
- **RED** — 3+ CRITICAL findings OR compliance < 2/4
