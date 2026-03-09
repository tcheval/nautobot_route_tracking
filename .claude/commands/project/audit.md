---
name: audit
description: Deep project audit with specialized agents
arguments: $1
---

# Audit

Perform a comprehensive project audit using specialized agents running in parallel.

## Agents Invoked

1. **code-reviewer** — Code quality, conventions, anti-patterns
2. **documentation-reviewer** — Documentation completeness, accuracy, language

## Scope

- `all` (default) — Full project audit
- `src` — Focus on source code only
- `docs` — Focus on documentation only

## Execution

Launch agents in parallel using `run_in_background: true`.

### Phase 1: Code Quality Audit

Ask `code-reviewer` agent:

```text
Review code quality across the project:
- Naming conventions (files, functions, variables, classes)
- Code structure and organization
- Error handling patterns
- DRY violations and duplication
- Security concerns (hardcoded secrets, injection risks)
- Nautobot 3.x compliance (validated_save, PrimaryModel, register_jobs)
- Nornir/NAPALM patterns (napalm_cli only, no napalm_get, parallel nr.run)
Read: _convention/_core.md, then _convention/_nautobot-plugin.md
Focus on: nautobot_route_tracking/, tests/
Rate severity: CRITICAL / WARNING / INFO with file paths and line numbers.
```

### Phase 2: Documentation Audit

Ask `documentation-reviewer` agent:

```text
Review documentation quality:
- README Guard: every structural directory must have README.md
- Language compliance: all .md files must be in English
- Documentation accuracy: do READMEs match actual contents?
- CHANGELOG presence and format
- Root README completeness (purpose, setup, usage)
- CLAUDE.md completeness and accuracy
Rate severity: CRITICAL / WARNING / INFO with file paths.
```

## Output

Generate a consolidated report:

```markdown
# Project Audit Report

## Executive Summary
- Critical issues: X
- Warnings: X
- Recommendations: X

## Code Quality (code-reviewer)
[findings]

## Documentation (documentation-reviewer)
[findings]

## Recommended Actions
| Priority | Area | Issue | Fix |
|----------|------|-------|-----|
| CRITICAL | ... | ... | ... |
| WARNING | ... | ... | ... |
```

### Save Report (mandatory)

Save the report to `reports/audit/`:

```bash
ls reports/audit/  # verify directory exists
```

Save as `reports/audit/audit_YYYYMMDD.md` (use current date).

### Sync Findings

After saving, sync new findings to the registry:

```bash
python scripts/findings.py sync
```
