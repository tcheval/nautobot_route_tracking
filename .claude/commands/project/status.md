---
name: status
description: "Single-screen project status dashboard"
---

# /project:status — Project Dashboard

## Purpose

Display a single-screen view of the project's current state: version, quality, findings, compliance, latest audit, and git status.

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

4. **Latest audit** — Find and read the most recent audit report:

```bash
ls -t reports/audit/audit_*.md 2>/dev/null | head -1
```

Read the first 15 lines to extract the title, date, and score.

5. **Open findings** — Read `reports/findings/registry.yml` and count findings where `status: open`, grouped by severity. If registry doesn't exist, show "No findings registry — run `/project:findings sync`".

### Step 2: Format Output

Present the data using this format:

```markdown
# Project Status

Health: GREEN (score 8.5/10)

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

## Latest Audit

**<audit_title>** — <date>
Score: X/10 | Criticals: N | Warnings: N

## Git Status

<output of git status --short, or "Clean working tree">

### Recent Commits

<last 5 commits from git log --oneline>
```

### Step 3: Health Indicator

At the top of the output, add a health indicator based on:

- **GREEN** — 0 CRITICAL findings, compliance >= 3/4
- **YELLOW** — 1-2 CRITICAL findings OR compliance 2/4
- **RED** — 3+ CRITICAL findings OR compliance < 2/4

The score comes from the latest audit report if available, otherwise omit it.

Display as:

```markdown
Health: GREEN (score 8.5/10)
```
