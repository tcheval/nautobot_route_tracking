---
name: review
description: Review previous audit and track remediation progress
arguments: $1
---

# Review

Review a previous audit report and track remediation progress.

## Execution

### Step 1: Load Previous Report

```bash
# If no argument, find latest
ls -t reports/audit/*.md 2>/dev/null | head -1

# Or use specified file
cat reports/audit/$1
```

If no report found, display: "No audit reports found. Run `/project:audit` first."

### Step 2: Cross-Reference Findings Registry

Load the findings registry and compare with audit report:

```bash
python scripts/findings.py show --all
```

Check which audit findings have been added to the registry and which are missing. Add any missing findings:

```bash
python scripts/findings.py sync
```

### Step 3: Parse Action Items

Extract all items from "Recommended Actions" table:

- CRITICAL
- WARNING
- INFO

### Step 4: Check Remediation Status

For each action item, verify if it has been addressed by checking the codebase:

```text
| Issue | Status | Evidence |
|-------|--------|----------|
| "Missing validation for X" | FIXED | file exists at expected path |
| "Hardcoded value in Y" | OPEN | file:line still has the issue |
```

For fixed items, resolve them in the registry:

```bash
python scripts/findings.py resolve F-XXX --reason "Fixed in commit <hash>"
```

### Step 5: Generate Review Report

```markdown
# Audit Review

## Report Reviewed
- File: <path>
- Original Date: <date>
- Review Date: <today>

## Remediation Progress

| Priority | Total | Fixed | Open |
|----------|-------|-------|------|
| CRITICAL | X | X | X |
| WARNING | X | X | X |
| INFO | X | X | X |

## Still Open

### CRITICAL
- [ ] Issue description

### WARNING
- [ ] Issue description

## Completed Since Last Audit
- [x] Fixed: description

## Recommendation
- Fix remaining CRITICAL items, then re-run `/project:audit`
```

### Step 6: Display Findings Summary

```bash
python scripts/findings.py stats
```

## Workflow

```text
/project:audit           # Initial audit
# ... fix issues ...
/project:review          # Check progress
# ... fix more ...
/project:review          # Verify all done
```
