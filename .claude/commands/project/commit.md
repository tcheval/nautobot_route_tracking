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
python3 -m ruff check nautobot_route_tracking/ tests/ scripts/ --output-format concise
```

If lint fails, STOP. Display: "Fix lint errors before committing."

### Step 2a: Run Format Check (Guard)

```bash
python3 -m ruff format --check nautobot_route_tracking/ tests/ scripts/
```

If format check fails, STOP. Display: "Fix formatting before committing. Run: ruff format ."

### Step 3: Run Tests (Guard)

```bash
python3 -m pytest tests/ scripts/tests/ -q --tb=line
```

If tests fail, STOP. Display: "Fix failing tests before committing."

### Step 4: Stage Changes

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

### Step 5: Analyze Changes

Determine commit type based on changed files:

| Files Changed | Suggested Type |
| ------------- | -------------- |
| Source code (`nautobot_route_tracking/`) | `feat` or `fix` |
| Tests only | `test` |
| Documentation | `docs` |
| Config/tooling | `chore` |
| Restructure | `refactor` |

### Step 6: CHANGELOG Guard

If staged files include source code changes (`feat` or `fix`):

1. Read `CHANGELOG.md` current version
2. Determine version bump:
   - **Major** (X.0): breaking changes
   - **Minor** (x.Y): new features
   - **Patch** (x.y.Z): bug fixes
3. Update `CHANGELOG.md` with new version section
4. Stage `CHANGELOG.md`

Skip for `docs`-only or `chore`-only commits. Skip if no `CHANGELOG.md` exists.

### Step 6b: Badges Sync

If `CHANGELOG.md` was updated with a new version:

1. Read `README.md`
2. Update the version badge to match new version
3. Stage `README.md`

### Step 7: Generate Commit Message

```bash
git diff --cached --stat
git diff --cached
```

#### Format

```text
<type>(<scope>): v<version> — <summary>

- <change 1>
- <change 2>

Co-Authored-By: Claude <model> <noreply@anthropic.com>
```

> **Note:** The `Co-Authored-By` trailer uses the current model name (e.g., `Claude Opus 4.6`). Update the model name if the active model changes.

**Rules:**

- Header: max 72 chars, imperative mood, lowercase after colon
- **Include version in header** when CHANGELOG was updated (e.g., `feat(jobs): v1.3.0 — add purge old routes command`)
- Body: one bullet per logical change
- Trailer: always include Co-Authored-By
- Blank line between header, body, and trailer

### Step 8: Commit

```bash
git commit -m "$(cat <<'EOF'
<type>(<scope>): v<version> — <summary>

- <change 1>
- <change 2>

Co-Authored-By: Claude <model> <noreply@anthropic.com>
EOF
)"
```

### Step 8b: Smart Tagging

If staged files include source directories (`nautobot_route_tracking/`, `scripts/`, `tests/`, `_convention/`):

1. Extract new version from CHANGELOG.md
2. Create tag:

```bash
git tag v<VERSION> <commit-hash>
```

Otherwise (docs-only or chore-only with no source files):

```text
No tag (no source files changed)
```

### Step 8c: Full Release Workflow

Only if `release` argument is present **AND** a tag was created in Step 8b.

#### If on a feature branch:

1. Push the branch:

```bash
git push -u origin <branch>
git push origin v<version>
```

2. Create PR targeting `main`:

```bash
gh pr create --title "<commit-header>" --body "$(cat <<'EOF'
## Summary
<bullet points from commit body>

## Test Plan
- [ ] Lint and tests pass
- [ ] Review changes on affected components
EOF
)"
```

3. Merge PR and delete remote branch:

```bash
gh pr merge <pr-number> --merge --delete-branch
```

4. Move tag to the merge commit on main:

```bash
git tag -d v<version>
git push origin :refs/tags/v<version>
git tag v<version> <merge-commit-hash>
git push origin v<version>
```

5. Delete local feature branch:

```bash
git branch -d <branch>
```

#### If already on `main`:

1. Push branch and tag:

```bash
git push origin main
git push origin v<version>
```

#### Then (both cases): Create GitHub release

1. Find the previous RELEASE tag:

```bash
gh release list --limit 1 --json tagName -q '.[0].tagName'
```

2. Generate diff artifact:

```bash
git diff --name-only <last_release_tag>..v<version> | zip -@ release-v<version>-diff.zip
```

3. Build wheel and create GitHub release:

```bash
python3 -m build --wheel --sdist
gh release create v<version> dist/*.whl dist/*.tar.gz release-v<version>-diff.zip \
  --title "v<version>" \
  --notes "$(git log <last_release_tag>..v<version> --pretty=format:'- %s' --no-merges)"
```

4. Clean up:

```bash
rm release-v<version>-diff.zip
```

### Step 9: Summary

```text
=== Commit Summary ===
Type: <type>
Scope: <scope>
Message: <full header>

Files committed:
  <file list>

Commit: <hash>
PR: https://github.com/tcheval/nautobot_route_tracking/pull/<n>  (if release, feature branch)
Release: https://github.com/tcheval/nautobot_route_tracking/releases/tag/v<version>  (if release)

Next: git push origin <branch>
```

## Arguments

```bash
/project:commit              # Standard commit (tag auto if source files changed)
/project:commit fix          # Force type "fix"
/project:commit docs         # Force type "docs"
/project:commit push         # Commit + push (no PR, no release)
/project:commit release      # Full release: commit → push → PR → merge → tag → GitHub release
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
- Will NOT commit if tests fail
- Will NOT force push
- Always shows diff before confirming
