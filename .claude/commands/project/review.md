---
name: review
description: Review previous audit/analysis and track remediation progress
arguments: $1
---

# Review

Review a previous audit or analysis report and track remediation progress.

## Purpose

- Follow up on audit findings
- Check what has been fixed
- Update remediation status
- Cross-reference with the findings registry

## Execution

### Step 1: Load Previous Report

```bash
# If no argument, find latest
ls -t reports/audit/*.md 2>/dev/null | head -1

# Or use specified file
cat reports/audit/$1
```

If no report found, display: "No audit reports found. Run `/project:audit` first."

### Step 2: Parse Action Items

Extract all items from "Recommended Actions" or "Action Items" tables:

- CRITICAL
- WARNING
- INFO

### Step 3: Cross-Reference Findings Registry

Read `reports/findings/registry.yml` if it exists and cross-reference with the audit report:

- Match audit findings to registry entries by title/file
- Identify findings that have been resolved since the audit
- Identify new findings not yet in the registry (suggest `/project:findings sync`)
- If registry doesn't exist or is empty, note: "Findings registry empty — run `/project:findings sync` to populate"

### Step 4: Check Remediation Status

For each action item, verify if it has been addressed:

```text
| Issue | Status | Evidence | Finding ID |
|-------|--------|----------|------------|
| "Missing validation for X" | FIXED | file exists at expected path | F-012 |
| "Hardcoded value in Y" | OPEN | file:line still has the issue | F-003 |
```

For each item:

- Check if the file/code mentioned still has the issue
- If a matching Finding ID exists in the registry, include it
- Mark as FIXED or OPEN based on evidence

For fixed items, resolve them in the registry:

```bash
python3 scripts/findings.py resolve F-XXX --reason "Fixed in commit <hash>"
```

### Step 5: Generate Review Report

```markdown
# Audit Review

## Report Reviewed
- File: reports/audit/audit_20260313.md
- Original Date: 2026-03-13
- Review Date: 2026-03-20

## Findings Registry Status

| Metric | Value |
| --- | --- |
| Total findings | N |
| Open | N |
| Resolved | N |
| Resolution rate | N% |
| From this audit | N (N open, N resolved) |

## Remediation Progress

| Priority | Total | Fixed | Open |
|----------|-------|-------|------|
| CRITICAL | X | X | X |
| WARNING | X | X | X |
| INFO | X | X | X |

## Still Open

### CRITICAL
- [ ] Issue description -> file:line (Finding ID: F-NNN)

### WARNING
- [ ] Issue description -> file:line (Finding ID: F-NNN)

## Completed Since Last Audit
- [x] Fixed: description (F-NNN)
- [x] Fixed: description (F-NNN)

## Recommendation
- Run `/project:audit` again after fixing remaining CRITICAL items
- Run `/project:findings sync` if new findings detected not in registry
```

Save to `reports/audit/review_<timestamp>.md`

### Step 6: Display Findings Summary

```bash
python3 scripts/findings.py stats
```

## Workflow

```text
/project:audit           # Initial audit
# ... fix issues ...
/project:review          # Check progress
# ... fix more ...
/project:review          # Verify all done
/project:findings stats  # Overall findings health
/project:status          # Full project dashboard
```
