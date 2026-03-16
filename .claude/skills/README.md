# Skills

Reusable domain knowledge loaded automatically based on work scope.

## How to Add a Skill

1. Create a directory under `.claude/skills/<skill-name>/`
2. Add a `SKILL.md` file with the domain knowledge
3. Reference the skill in `CLAUDE.md` under "Skill Auto-Loading"

## Skill Structure

```text
.claude/skills/
└── my-domain/
    └── SKILL.md    # Domain knowledge, patterns, conventions
```

## SKILL.md Format

```markdown
# Skill: <Name>

<Description of what this skill provides>

## Patterns

<Code patterns, conventions, examples for this domain>

## Anti-patterns

<What NOT to do>

## Reference

<Links, specs, or lookup tables>
```

## Auto-Loading

Add an entry to `CLAUDE.md` to auto-load skills when touching specific files:

```markdown
| Files touched | Skill to load |
| --- | --- |
| `nautobot_route_tracking/jobs/` | `nornir-collection` |
```
