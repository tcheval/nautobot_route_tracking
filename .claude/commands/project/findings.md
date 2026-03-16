---
name: findings
description: "Manage audit findings registry — show, add, resolve, stats, sync"
arguments:
  - $1
---

# /project:findings — Findings Registry Manager

## Input

Action: `$1` (one of: `show`, `add`, `resolve`, `stats`, `sync`)

## Registry Location

`reports/findings/registry.yml`

## Actions

### show (default)

Display findings from the registry.

**Steps:**

1. Read `reports/findings/registry.yml`
2. Parse arguments for optional filters:
   - `--severity CRITICAL|HIGH|WARNING|INFO` — filter by severity
   - `--status open|partial|resolved|wont_fix` — filter by status (default: `open`)
   - `--category <name>` — filter by category
   - `--audit <audit_name>` — filter by source audit
   - `--all` — show all findings regardless of status
3. Display as markdown table:

```text
| ID | Severity | Category | Title | Status | Age |
```

4. Show summary count at bottom

### add

Add a new finding interactively.

**Steps:**

1. Read `reports/findings/registry.yml` to get next ID
2. Ask user for:
   - severity (CRITICAL, HIGH, WARNING, INFO)
   - category
   - title
   - description
   - file (optional)
3. Generate ID: `F-NNN` (next sequential number)
4. Set status: `open`, resolution: `null`, resolved_date: `null`
5. Set date to today, source_audit to `manual`
6. Append to registry.yml

### resolve

Mark a finding as resolved.

**Steps:**

1. Parse finding ID from arguments (e.g., `resolve F-028`)
2. Read `reports/findings/registry.yml`
3. Find the matching finding
4. Ask user for resolution description
5. Update:
   - `status: resolved`
   - `resolution: <user input>`
   - `resolved_date: <today>`
6. Write back to registry.yml

### stats

Display summary statistics.

**Steps:**

1. Read `reports/findings/registry.yml`
2. Calculate and display:

```markdown
## Findings Summary

| Metric | Value |
| --- | --- |
| Total findings | N |
| Open | N |
| Resolved | N |
| Partial | N |
| Won't fix | N |
| Resolution rate | N% |

## By Severity (open only)

| Severity | Count |
| --- | --- |
| CRITICAL | N |
| HIGH | N |
| WARNING | N |
| INFO | N |

## By Category (open only)

| Category | Count |
| --- | --- |

## By Source Audit

| Audit | Total | Open | Resolved |
| --- | --- | --- | --- |

## Aging (open findings)

| Age Range | Count |
| --- | --- |
| < 7 days | N |
| 7-30 days | N |
| > 30 days | N |
```

### sync

Parse audit reports and upsert new findings.

**Steps:**

1. Read all `reports/audit/audit_*.md` files
2. Read current `reports/findings/registry.yml`
3. For each audit report:
   - Extract findings from CRITICAL/WARNING/HIGH tables and sections
   - Extract from "Recommended Actions" or "Action Items" tables
   - Generate candidate findings with: title, severity, file, description
4. Compare against existing registry (match by title similarity + file)
5. For new findings only:
   - Assign next sequential ID
   - Set status: `open`
   - Set `source_audit` to the audit filename (e.g., `audit_2026-03-13`)
   - Append to registry
6. Update `metadata.last_sync` to today
7. Report: "Synced N audit files. Added M new findings. N existing findings unchanged."

**Matching rules:**

- A finding is considered "existing" if title matches > 80% similarity AND file matches
- Never overwrite existing findings (status, resolution are user-managed)
- Deduplicate across audits (same finding in multiple audits = single entry)

## Finding Schema

Each finding in the registry has these fields:

```yaml
- id: "F-001"
  source_audit: "audit_2026-03-13"
  date: "2026-03-13"
  severity: "CRITICAL"
  category: "code"
  title: "Missing error handling in service client"
  description: "The HTTP client does not handle connection timeouts"
  file: "nautobot_route_tracking/client.py"
  status: "open"
  resolution: null
  resolved_date: null
```

## Output Format

Always display findings as clean markdown tables. Use severity colors in output:

- CRITICAL findings listed first
- Group by severity descending (CRITICAL > HIGH > WARNING > INFO)
