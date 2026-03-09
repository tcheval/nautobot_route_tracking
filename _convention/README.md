# Convention Starter Kit

A ready-to-use convention framework for Claude Code projects. Provides universal design principles, a domain convention template, and a pre-configured CLAUDE.md.

## Quickstart

```bash
# 1. Copy the starter into your project
cp -r convention-starter/_convention/ your-project/_convention/
cp convention-starter/CLAUDE.md your-project/CLAUDE.md
cp convention-starter/CHANGELOG.md your-project/CHANGELOG.md

# 2. Customize CLAUDE.md
#    - Replace project name, stack, owner
#    - Add project-specific hard rules
#    - Update project structure diagram
#    - Follow the CUSTOMIZE comments

# 3. Create your first domain convention
cp _convention/_domain-template.md _convention/_backend.md
#    - Fill in the 6 sections (follow the minimum viable guides)
#    - Add to _convention/README.md table
#    - Add loading instruction to CLAUDE.md

# 4. Validate (optional, if you have the review plugin)
/review-memory
/review-convention
```

## What's Included

```text
CLAUDE.md                           # Claude Code instruction set (customize this)
CHANGELOG.md                        # Convention change history

_convention/
├── README.md                       # Convention governance and hierarchy
├── _core.md                        # Universal principles (immutable)
└── _domain-template.md             # Template for new domain conventions
```

## Design Decisions

**Why a separate `_convention/` directory?** Conventions are reference documents, not code. Keeping them separate from source code makes them easy to find, review, and version independently.

**Why `_core.md` is immutable?** Core principles (KISS, YAGNI, DRY, etc.) are universal. If a domain convention could override them, you'd end up with inconsistent principles across domains. Core sets the floor, domains build on top.

**Why decision tests in `_core.md`?** Principles without verification criteria are decorative. "Keep it simple" means nothing actionable. "Can you remove a layer and still achieve the same result? If yes, remove it" is a decision you can actually make.

**Why the domain template has minimums?** A convention file with "## Architecture" and nothing under it is worse than no convention — it gives a false sense of coverage. The minimum viable guides prevent empty sections.
