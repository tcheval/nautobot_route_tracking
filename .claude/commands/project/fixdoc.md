---
name: fixdoc
description: Fix markdown formatting errors and translate documentation to English
arguments: $1
---

# Fix Documentation

Lint, fix, and translate all markdown files to English.

## Prerequisites

- `markdownlint` CLI installed (`brew install markdownlint-cli`)

## Execution

### Step 1: Detect errors

Run markdownlint on all tracked markdown files (excluding vendor/generated):

```bash
markdownlint --ignore node_modules --ignore .venv --ignore .claude --ignore reports "**/*.md" 2>&1 || true
```

If `$1` is provided, scope to that path instead:

```bash
markdownlint "$1" 2>&1 || true
```

### Step 2: Auto-fix what markdownlint can fix

```bash
markdownlint --fix --ignore node_modules --ignore .venv --ignore .claude --ignore reports "**/*.md" 2>&1 || true
```

### Step 3: Fix remaining issues manually

For errors that `--fix` cannot handle automatically:

1. Read each file with remaining errors
2. Fix issues:
   - **MD040** — Add language to fenced code blocks (`text`, `bash`, `yaml`, `json`, `python`, `toml`)
   - **MD060** — Add spaces around pipes in table separator rows: `|---|` → `| --- |`
   - **MD032** — Add blank lines around lists
   - **MD047** — Ensure files end with a single newline

### Step 3b: Add Table of Contents

For each README.md file with 3 or more `##` sections, ensure a Table of Contents exists after the top-level heading:

1. If no TOC exists, generate one from `##` headings using markdown links
2. If a TOC already exists, verify it matches the current headings and update if needed
3. Format:

```markdown
## Table of Contents

- [Section One](#section-one)
- [Section Two](#section-two)
```

### Step 4: Translate to English

Scan all modified/fixed markdown files for non-English content:

1. Read each `.md` file (excluding `_convention/`)
2. If the file contains French prose (descriptions, headers, paragraphs), translate to English
3. Preserve:
   - Technical terms, code identifiers, CLI commands (keep as-is)
   - YAML/code blocks (keep as-is)
   - File paths and references (keep as-is)
   - Proper nouns (keep as-is)

### Step 5: Re-validate

```bash
markdownlint --ignore node_modules --ignore .venv --ignore .claude --ignore reports "**/*.md" 2>&1 || true
python3 scripts/fixdoc.py --check
```

## Output Summary

```text
=== Fix Documentation Summary ===
Scope: $1 (or "all *.md")
Files scanned: X
Errors found: Y
Auto-fixed: Z
Manual fixes: W
Translated: T files

Remaining issues (if any):
  - file.md:line: description
```

## Rules

- All documentation MUST be written in English (CLAUDE.md rule)
- All code comments MUST be in English (CLAUDE.md rule)
- Code blocks MUST have a language specified (MD040)
- Tables MUST use `| value |` format with spaces around pipes (MD060)
- Files MUST end with a single newline (MD047)
