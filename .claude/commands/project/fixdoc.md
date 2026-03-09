---
name: fixdoc
description: Fix markdown formatting errors and check language compliance
arguments: $1
---

# Fix Documentation

Lint, fix, and verify language compliance of all markdown files.

**Prerequisites:** `brew install markdownlint-cli`

## Execution

### Step 1: Detect errors

```bash
markdownlint --ignore node_modules --ignore .venv --ignore .claude --ignore reports "**/*.md"
```

### Step 2: Auto-fix

```bash
markdownlint --fix --ignore node_modules --ignore .venv --ignore .claude --ignore reports "**/*.md"
```

### Step 3: Manual fixes

Some errors cannot be auto-fixed. Read each flagged file and fix manually:

- **MD040** — Add language tag to fenced code blocks
- **MD060** — Add spaces around pipes in table separator rows
- **MD032** — Add blank lines around lists
- **MD047** — Ensure files end with a single newline

### Step 4: Language check

```bash
python3 scripts/fixdoc.py $1
```

If language warnings are reported, read each flagged file and translate non-English content to English. Preserve technical terms, code blocks, and identifiers.

### Step 5: Re-validate

```bash
markdownlint --ignore node_modules --ignore .venv --ignore .claude --ignore reports "**/*.md"
python3 scripts/fixdoc.py --check
```

## Rules

- All documentation MUST be in English
- All code comments MUST be in English
- Code blocks MUST have a language tag
- Files MUST end with a single newline
