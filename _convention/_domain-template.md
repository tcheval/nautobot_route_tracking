# Convention: [Domain Name]

> **Version:** 0.1
> **Scope:** [What this domain covers — one sentence]
> **Requires:** `_convention/_core.md`

**Extends core:** This file adds domain-specific rules. It NEVER overrides `_core.md` principles.

---

## Table of Contents

- [1. Architecture](#1-architecture)
- [2. Data Model](#2-data-model)
- [3. Naming Conventions](#3-naming-conventions)
- [4. Patterns](#4-patterns)
- [5. Anti-patterns](#5-anti-patterns)
- [6. Validation Rules](#6-validation-rules)

---

## 1. Architecture

<!-- MINIMUM VIABLE: Describe components, their responsibilities, and data flow.
     Include at least one diagram showing component boundaries.
     A reader should understand WHAT exists and HOW it connects.

     Example (replace with your domain): -->

```text
[Component A] → [Component B] → [Component C]
   (role)           (role)           (role)
```

| Component | Responsibility | Inputs | Outputs |
| --------- | -------------- | ------ | ------- |
| [Name] | [One-sentence role] | [What it receives] | [What it produces] |
| [Name] | [One-sentence role] | [What it receives] | [What it produces] |

### Boundary Rules

<!-- What does this domain own? What does it NOT own?
     This prevents scope creep and clarifies agent boundaries. -->

- **Owns:** [list what this domain controls]
- **Does NOT own:** [list what belongs to other domains]
- **Depends on:** [list other domains this one calls or imports from]

---

## 2. Data Model

<!-- MINIMUM VIABLE: Define every data structure this domain uses.
     Required fields, types, constraints, and relationships.
     This is the contract — other domains depend on it.

     Example (replace with your domain): -->

### 2.1 [Model Name]

| Field | Type | Required | Default | Description |
| ----- | ---- | -------- | ------- | ----------- |
| `id` | string | yes | — | Unique identifier (UUID) |
| `name` | string | yes | — | Human-readable name |
| `status` | enum | yes | `"active"` | One of: `active`, `inactive`, `error` |
| `metadata` | object | no | `{}` | Arbitrary key-value pairs |

**Constraints:**

- `id` must be globally unique
- `name` must be non-empty, max 255 characters
- `status` transitions: `active` ↔ `inactive`, `* → error` (one-way)

### Relationships

<!-- How does this model relate to models in other domains? -->

```text
[This Model] 1──N [Related Model]    (via field_name)
[This Model] N──1 [Parent Model]     (via parent_id)
```

---

## 3. Naming Conventions

<!-- MINIMUM VIABLE: Cover files, directories, variables/fields, functions/methods.
     Every entry needs a pattern AND a concrete example.

     Example (replace with your domain): -->

| Category | Pattern | Good Example | Bad Example |
| -------- | ------- | ------------ | ----------- |
| Files | `snake_case.ext` | `user_service.py` | `UserService.py` |
| Directories | `snake_case/` | `data_models/` | `DataModels/` |
| Functions | `verb_noun` | `get_user()` | `user()` |
| Constants | `SCREAMING_SNAKE` | `MAX_RETRIES` | `maxRetries` |
| Config keys | `kebab-case` | `api-timeout` | `apiTimeout` |

---

## 4. Patterns

<!-- MINIMUM VIABLE: At least 2 patterns. Each with:
     - WHEN to use it (trigger condition)
     - WHY it's preferred (benefit)
     - HOW it looks (code/config example)

     Example (replace with your domain): -->

### 4.1 [Pattern Name]

**When:** [Trigger condition — when should you reach for this pattern?]

**Why:** [What problem it solves, what principle it supports (reference _core.md)]

```python
# Example implementation
def example():
    pass
```

### 4.2 [Pattern Name]

**When:** [Trigger condition]

**Why:** [Benefit, linked to core principle]

```python
# Example implementation
def example():
    pass
```

---

## 5. Anti-patterns

<!-- MINIMUM VIABLE: At least 2 anti-patterns. Each with:
     - The BAD code/config (what people actually do wrong)
     - WHY it's bad (what breaks, which principle it violates)
     - The GOOD fix (corrected version)

     Example (replace with your domain): -->

### 5.1 [Anti-pattern Name]

**Problem:** [What goes wrong — be specific about the failure mode]

**Violates:** [Reference to `_core.md` principle, e.g., "1.11 Fail Loud, Fail Early"]

```python
# BAD
def process(data):
    try:
        result = transform(data)
    except Exception:
        return None  # Silent failure — caller has no idea what happened
```

**Fix:**

```python
# GOOD
def process(data):
    result = transform(data)  # Let it raise — fail loud
    return result
```

### 5.2 [Anti-pattern Name]

**Problem:** [What goes wrong]

**Violates:** [Core principle reference]

```python
# BAD — example
```

**Fix:**

```python
# GOOD — example
```

---

## 6. Validation Rules

<!-- MINIMUM VIABLE: List every rule that should be checked automatically.
     Each rule needs: what to check, how to check it, and what severity a violation carries.

     Severity levels:
     - CRITICAL: Blocks build/deploy. Must fix before merge.
     - WARNING:  Should fix. Allowed temporarily with justification.
     - INFO:     Improvement opportunity. Fix when convenient.

     Example (replace with your domain): -->

| # | Rule | Check Method | Severity |
| - | ---- | ------------ | -------- |
| 1 | [Rule description] | [How to verify: lint rule, grep, test, CI step] | CRITICAL |
| 2 | [Rule description] | [How to verify] | WARNING |
| 3 | [Rule description] | [How to verify] | INFO |

### Automated Enforcement

<!-- Which of the above rules are currently enforced by tooling? -->

| Rule # | Enforcement | Tool/Config |
| ------ | ----------- | ----------- |
| 1 | ✅ Enforced | `ruff.toml` rule T201 |
| 2 | ⚠️ Partial | Test exists but not in CI |
| 3 | ❌ Manual | Not yet automated |
