# Scripts

Utility scripts for project management and quality assurance.

## Available Scripts

| Script | Description | Usage |
| ------ | ----------- | ----- |
| `metrics.py` | Project health metrics | `python scripts/metrics.py [--json] [--save] [--compare]` |
| `findings.py` | Findings registry manager | `python scripts/findings.py {show,add,resolve,stats,sync}` |
| `fixdoc.py` | Markdown lint, fix, and language check | `python scripts/fixdoc.py [path]` |

These scripts are also available via slash commands: `/project:metrics`, `/project:findings`, `/project:fixdoc`.
