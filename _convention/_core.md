# Convention Core — Universal Principles

> **Version:** 2.0
> **Scope:** Universal principles for all project domains
> **Audience:** LLM agents, Architects, Maintainers

**Boundary rule:** If a rule requires knowledge of specific protocols, frameworks, or platform behavior, it does not belong in this document — it belongs in a domain convention.

**Hierarchy rule:** Core principles are **immutable**. Domain conventions extend core but NEVER override it. Conflicts → core wins unconditionally.

---

## Table of Contents

- [1. Design Principles](#1-design-principles)
- [2. Data Model Hierarchy](#2-data-model-hierarchy)
- [3. Validation Philosophy](#3-validation-philosophy)
- [4. Execution Principles](#4-execution-principles)
- [5. Convention Governance](#5-convention-governance)

---

## 1. Design Principles

Every principle includes a **decision test** — a concrete way to verify compliance.

### 1.1 KISS — Keep It Simple

Prefer the simplest structure that works. No unnecessary layers, no meta-abstractions.

**Decision test:** Can you remove a layer, wrapper, or abstraction and still achieve the same result? If yes, remove it.

**Violation signals:**

- A module/class with fewer than 2 callers
- A wrapper that adds no logic (just delegates)
- An abstraction created "for future flexibility" with only one implementation

### 1.2 YAGNI — You Aren't Gonna Need It

Do not add features, fields, or logic unless actually required by a current task.

**Decision test:** Is there a current user story, test case, or requirement that needs this? If not, delete it.

**Violation signals:**

- Code paths with no tests and no callers
- Configuration fields that are always set to their default
- "Extensibility hooks" that nothing hooks into

### 1.3 DRY — Don't Repeat Yourself

Shared logic lives in one place. Domain-specific logic lives only in domain-specific modules.

**Decision test:** Does changing this fact/logic require edits in more than one file? If yes, extract to a single source.

**Violation signals:**

- Same constant defined in 2+ files
- Same validation logic implemented in 2+ places
- Copy-pasted blocks with minor variations

**Exception:** Duplication is acceptable when the alternative would create a coupling dependency that violates Separation of Concerns (1.6). Prefer loose coupling over aggressive DRY.

### 1.4 RFC 1925 — Rule 12

> "Perfection is reached not when there is nothing left to add, but when there is nothing left to take away."

**Decision test:** For every element (field, function, file, config key), ask: what breaks if I remove this? If nothing breaks, remove it.

### 1.5 Single Source of Truth

Each piece of information exists in exactly one location. Reference, don't copy.

**Decision test:** Search the project for the same fact. If it appears in 2+ places, one must become a reference to the other.

**Violation signals:**

- Same default value defined in code AND config AND docs
- A README that restates rules from a convention file
- Constants duplicated across modules

### 1.6 Separation of Concerns

Each layer has a clear responsibility. Data defines intent. Logic transforms. Output stores results.

**Decision test:** Can you describe a module's responsibility in one sentence without using "and"? If not, split it.

**Violation signals:**

- A function that both validates AND transforms
- A data file that contains logic (computed fields, conditionals)
- A module that imports from 3+ different architectural layers

### 1.7 Explicit Over Implicit

Prefer explicit configuration over convention-based inference. Naming must reflect intent.

**Decision test:** Can a new team member understand what this does without reading the implementation? If not, make it explicit.

**Violation signals:**

- Behavior that changes based on environment variables not documented in config
- Function names that don't describe their side effects
- "Magic" defaults that differ from what a reader would expect

### 1.8 Predictable Output

Same input produces the same output. Minimize hidden environment dependencies.

**Decision test:** Run the same operation twice with unchanged input. Is the output identical (byte-for-byte where applicable)? If not, document why.

**Violation signals:**

- Output that includes timestamps, random IDs, or system-specific paths without explicit opt-in
- Results that change based on execution order
- Hidden dependency on system locale, timezone, or OS

### 1.9 Human-Friendly Diffs

Data structures must be easy to diff. Prefer flat structures, one logical item per line.

**Decision test:** Change one field in the data. Does `git diff` show exactly one line changed? If it shows noise (reordering, reformatting), restructure.

**Violation signals:**

- JSON with multiple values on one line
- Lists sorted by runtime order rather than stable sort
- Generated files without deterministic ordering

### 1.10 No Hidden Magic

No implicit behavior depending on external state or hidden logic. All transformations must be traceable.

**Decision test:** Can you trace from input to output by reading the code linearly, without needing to know about external triggers, hooks, or side-channel data? If not, make the dependency explicit.

**Violation signals:**

- Behavior that changes based on file existence (auto-detection)
- Import-time side effects (code that runs at module load)
- Configuration that silently falls back to defaults without warning

### 1.11 Fail Loud, Fail Early

If an assumption is missing or invalid, trigger a visible failure immediately. Silent fallbacks are forbidden.

**Decision test:** Introduce a deliberately bad input. Does the system fail immediately with a clear error message? Or does it silently produce wrong output?

**Violation signals:**

- `except: pass` or empty catch blocks
- Functions that return `None` on error instead of raising
- Default values that mask missing required configuration

---

## 2. Data Model Hierarchy

Variables follow strict precedence (most specific wins):

```text
Global defaults    →  Shared across all targets    (lowest priority)
Scope overrides    →  Group-specific parameters     (medium priority)
Target specifics   →  Individual target reality     (highest priority)
```

### Rules

- **Single Location:** Each piece of information exists in exactly ONE source location
- **Override direction:** Specific overrides general, never the reverse
- **Merge strategy:** Shallow merge by default. Deep merge only when explicitly documented
- **Conflict resolution:** If two sources define the same key at the same precedence level, this is an error — fail loud (1.11)

### Decision test

For any configuration value: can you point to exactly ONE file where it is defined? If it appears in two files at the same level, that's a violation.

---

## 3. Validation Philosophy

### 3.1 Audit, Then Fail

Validation collects ALL errors before failing — never abort on first error.

```text
1. Initialize empty error list
2. Each check appends failures to the list (does not abort)
3. Final step: if error list is non-empty → fail with complete report
4. User sees ALL problems in one pass
```

**Decision test:** Introduce 3 errors simultaneously. Does the validator report all 3, or only the first?

### 3.2 Error Message Format

Every error message MUST include these 4 elements:

| Element | Example |
| ------- | ------- |
| **Target** | `_convention/_backend.md` |
| **What failed** | Missing required section "Naming Conventions" |
| **Expected** | Section "## 3. Naming Conventions" present |
| **Actual** | Section not found |

**Anti-pattern:** `"Validation failed"` — no context, no actionability.

### 3.3 Comments Explain Why, Never What

Code should be self-documenting through naming and structure.

**Decision test:** Read a comment. Does it say what the code does (bad) or why it does it that way (good)?

```text
# BAD: Increment counter by one
counter += 1

# GOOD: Offset by 1 because the API uses 1-based indexing
counter += 1
```

---

## 4. Execution Principles

### 4.1 Idempotence

Running the same operation twice with unchanged input produces identical output.

**Decision test:** Execute the operation. Execute it again immediately. Is the output identical? Are there no side effects (duplicate files, double entries)?

**Violation signals:**

- Operations that append without checking for existence
- File creation without existence check
- ID generation without deduplication

### 4.2 Root-Relative Paths

All paths are relative to project root. No `../` references. No absolute paths.

**Decision test:** `grep -r '\.\.\/' .` should return zero results in project source files (excluding `node_modules`, `.git`, etc.).

**Violation signals:**

- `../../shared/utils.py` — use `shared/utils.py` from project root
- `/home/user/project/src/` — use `src/`
- Path construction that depends on the caller's location

### 4.3 Execution Context

All commands run from project root. Automation verifies context before execution.

**Decision test:** Does the command/script check that it's running from the expected directory before proceeding?

```bash
# Good: verify context
[ -f "CLAUDE.md" ] || { echo "Error: run from project root"; exit 1; }
```

---

## 5. Convention Governance

Rules for managing the conventions themselves.

### 5.1 Versioning

- Convention files use semantic versioning: `MAJOR.MINOR`
- MAJOR: breaking change (rule removed, rule semantics changed)
- MINOR: additive change (new rule, new example, clarification)
- Version is declared in the file header: `> **Version:** X.Y`

### 5.2 Change Process

1. Propose change with rationale
2. Update the convention file
3. Update CHANGELOG.md with the change
4. If a domain convention is affected by a core change, update it in the same commit

### 5.3 Core Immutability

Domain conventions MUST NOT:

- Redefine a core principle with different semantics
- Add exceptions to core rules without explicit core approval
- Use "override" language for core principles

Domain conventions MAY:

- Add domain-specific rules that extend core
- Provide domain-specific examples for core principles
- Define additional validation rules beyond core requirements
