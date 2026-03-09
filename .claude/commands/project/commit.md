---
name: commit
description: Stage and commit all pending changes with conventional commit message
arguments: $1
---

# Commit

Stage all changes and create a conventional commit with lint and test guards.

## Prerequisites

- Git repository initialized
- Changes pending (modified/untracked files)

## Execution

### Step 1: Check Status

```bash
git status --short
```

If no changes, exit with "Nothing to commit."

### Step 2: Run Lint (Guard)

```bash
python3 -m ruff check nautobot_route_tracking/ tests/
```

If lint fails, STOP. Display: "Fix lint errors before committing."

### Step 3: Stage Changes

Stage relevant files by name. **Never use `git add -A`** — it risks staging secrets or generated files.

```bash
git add nautobot_route_tracking/ tests/ scripts/ _convention/ docs/ .claude/
git add CLAUDE.md README.md CHANGELOG.md AGENTS.md
git add .gitignore .pre-commit-config.yaml pyproject.toml
```

Safety: NEVER stage `.env`, `credentials.json`, `*.pem`, `*.key`.

Verify staged files:

```bash
git diff --cached --name-only
```

### Step 4: Analyze Changes

Determine commit type based on changed files:

| Files Changed | Suggested Type |
| ------------- | -------------- |
| Source code (`nautobot_route_tracking/`) | `feat` or `fix` |
| Tests only | `test` |
| Documentation | `docs` |
| Config/tooling | `chore` |
| Restructure | `refactor` |

### Step 5: CHANGELOG Guard

If staged files include source code changes (`feat` or `fix`):

1. Read `CHANGELOG.md` current version
2. Determine version bump:
   - **Major** (X.0): breaking changes
   - **Minor** (x.Y): new features
   - **Patch** (x.y.Z): bug fixes
3. Update `CHANGELOG.md` with new version section
4. Stage `CHANGELOG.md`

Skip for `docs`-only or `chore`-only commits. Skip if no `CHANGELOG.md` exists.

### Step 5b: Badges Sync

If `CHANGELOG.md` was updated with a new version:

1. Read `README.md`
2. Update the version badge to match new version
3. Stage `README.md`

### Step 6: Generate Commit Message

```bash
git diff --cached --stat
git diff --cached
```

#### Format

```text
<type>(<scope>): <summary>

- <change 1>
- <change 2>

Co-Authored-By: Claude <model> <noreply@anthropic.com>
```

**Rules:**

- Header: max 72 chars, imperative mood, lowercase after colon
- Body: one bullet per logical change
- Trailer: always include Co-Authored-By
- Blank line between header, body, and trailer

### Step 7: Commit

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): <summary>

- <change 1>
- <change 2>

Co-Authored-By: Claude <model> <noreply@anthropic.com>
EOF
)"
```

### Step 7b: Smart Tagging

If staged files include source directories (`nautobot_route_tracking/`, `tests/`):

1. Extract new version from CHANGELOG.md
2. Create tag:

```bash
git tag v<VERSION> <commit-hash>
```

Otherwise (docs-only or chore-only with no source files):

```text
No tag (no source files changed)
```

### Step 7c: GitHub Release with diff artifact

Only if `release` argument is present **AND** a tag was created in Step 7b:

1. Find the previous RELEASE tag:

```bash
gh release list --limit 1 --json tagName -q '.[0].tagName'
```

2. Generate the diff file list and create zip:

```bash
git diff --name-only <last_release_tag>..HEAD | zip -@ release-v<version>-diff.zip
```

3. Build wheel and create GitHub release:

```bash
python3 -m build --wheel --sdist
gh release create v<version> dist/*.whl dist/*.tar.gz release-v<version>-diff.zip \
  --title "v<version>" \
  --notes "$(git log <last_release_tag>..HEAD --pretty=format:'- %s' --no-merges)"
```

4. Clean up:

```bash
rm release-v<version>-diff.zip
```

### Step 8: Summary

```text
=== Commit Summary ===
Type: <type>
Scope: <scope>
Message: <full header>

Files committed:
  <file list>

Commit: <hash>
Release: https://github.com/tcheval/nautobot_route_tracking/releases/tag/v<version>  (if release)

Next: git push origin <branch>
```

## Arguments

```bash
/project:commit              # Standard commit (tag auto if source files changed)
/project:commit fix          # Force type "fix"
/project:commit docs         # Force type "docs"
/project:commit release      # Commit + tag + GitHub release with wheel artifact
/project:commit push         # Commit + push
/project:commit push release # Commit + push + release
```

## Conventional Commit Types

| Type | When |
| ---- | ---- |
| `feat` | New feature |
| `fix` | Bug fix |
| `refactor` | Code change without feature/fix |
| `docs` | Documentation only |
| `chore` | Maintenance, configs, tooling |
| `test` | Adding or updating tests |

## Safety

- Will NOT commit if lint fails
- Will NOT force push
- Always shows diff before confirming
