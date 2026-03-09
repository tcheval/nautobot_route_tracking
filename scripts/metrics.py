#!/usr/bin/env python3
"""Project health metrics — counts source files, tests, findings, conventions, compliance."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def find_project_root() -> Path:
    """Find project root (directory containing CLAUDE.md)."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "CLAUDE.md").exists():
            return parent
    return cwd


def count_source_files(root: Path) -> int:
    """Count Python source files in nautobot_route_tracking/."""
    src = root / "nautobot_route_tracking"
    if not src.exists():
        return 0
    return len([f for f in src.rglob("*.py") if f.name != "__init__.py"])


def count_test_files(root: Path) -> int:
    """Count test files in tests/."""
    tests = root / "tests"
    if not tests.exists():
        return 0
    return len(list(tests.rglob("test_*.py")))


def count_test_functions(root: Path) -> int:
    """Count test functions (def test_*) across all test files."""
    tests = root / "tests"
    if not tests.exists():
        return 0
    count = 0
    for f in tests.rglob("test_*.py"):
        content = f.read_text(errors="ignore")
        count += len(re.findall(r"^\s*def test_", content, re.MULTILINE))
    return count


def count_conventions(root: Path) -> int:
    """Count convention files."""
    conv = root / "_convention"
    if not conv.exists():
        return 0
    return len([
        f for f in conv.glob("_*.md")
        if f.name != "_domain-template.md"
    ])


def count_agents(root: Path) -> int:
    """Count agent files."""
    agents = root / ".claude" / "agents"
    if not agents.exists():
        return 0
    return len(list(agents.glob("*.md")))


def count_commands(root: Path) -> int:
    """Count command files."""
    commands = root / ".claude" / "commands"
    if not commands.exists():
        return 0
    return len(list(commands.rglob("*.md")))


def load_findings(root: Path) -> dict[str, int]:
    """Load findings from registry and count by status."""
    registry = root / "reports" / "findings" / "registry.yml"
    result = {"open": 0, "resolved": 0, "total": 0}
    if not registry.exists():
        return result

    if yaml is not None:
        data = yaml.safe_load(registry.read_text()) or {}
    else:
        content = registry.read_text()
        result["open"] = len(re.findall(r"status:\s*open", content))
        result["resolved"] = len(re.findall(r"status:\s*resolved", content))
        result["total"] = result["open"] + result["resolved"]
        return result

    findings = data.get("findings") or []
    for f in findings:
        status = f.get("status", "open")
        if status == "open":
            result["open"] += 1
        elif status == "resolved":
            result["resolved"] += 1
    result["total"] = len(findings)
    return result


def check_compliance(root: Path) -> dict[str, bool]:
    """Run 4 compliance checks specific to nautobot_route_tracking."""
    checks: dict[str, bool] = {}

    # 1. No .save() — always validated_save()
    src = root / "nautobot_route_tracking"
    has_bare_save = False
    if src.exists():
        for py in src.rglob("*.py"):
            if py.name.startswith("0"):  # skip migrations
                continue
            content = py.read_text(errors="ignore")
            # Match .save() but not validated_save()
            if re.search(r"(?<!validated_)\.save\(\)", content):
                has_bare_save = True
                break
    checks["no_bare_save"] = not has_bare_save

    # 2. No napalm_get — always napalm_cli
    has_napalm_get = False
    if src.exists():
        for py in src.rglob("*.py"):
            content = py.read_text(errors="ignore")
            if "napalm_get" in content:
                has_napalm_get = True
                break
    checks["no_napalm_get"] = not has_napalm_get

    # 3. register_jobs() present in jobs/__init__.py
    jobs_init = src / "jobs" / "__init__.py" if src.exists() else None
    has_register = False
    if jobs_init and jobs_init.exists():
        content = jobs_init.read_text(errors="ignore")
        has_register = "register_jobs" in content
    checks["register_jobs"] = has_register

    # 4. English-only — no common French words in .md files
    non_english = False
    fr_words = re.compile(
        r"\b(également|c'est|n'est|utilisé|paramètre|créer|supprimé|"
        r"donc|aussi|cette|sont|pour|dans|avec|tous|peut|fait)\b",
        re.IGNORECASE,
    )
    for md in root.rglob("*.md"):
        if any(part.startswith(".") for part in md.parts):
            continue
        if "node_modules" in md.parts or ".venv" in md.parts:
            continue
        content = md.read_text(errors="ignore")
        if fr_words.search(content):
            non_english = True
            break
    checks["english_only"] = not non_english

    return checks


def collect_metrics(root: Path) -> dict:
    """Collect all metrics."""
    findings = load_findings(root)
    compliance = check_compliance(root)
    compliance_pass = sum(1 for v in compliance.values() if v)

    return {
        "source_files": count_source_files(root),
        "test_files": count_test_files(root),
        "test_functions": count_test_functions(root),
        "conventions": count_conventions(root),
        "agents": count_agents(root),
        "commands": count_commands(root),
        "findings_open": findings["open"],
        "findings_resolved": findings["resolved"],
        "findings_total": findings["total"],
        "compliance_pass": compliance_pass,
        "compliance_total": len(compliance),
        "compliance_details": {k: "PASS" if v else "FAIL" for k, v in compliance.items()},
    }


def display_metrics(metrics: dict) -> None:
    """Print metrics as markdown tables."""
    resolution_rate = 0
    if metrics["findings_total"] > 0:
        resolution_rate = round(
            metrics["findings_resolved"] / metrics["findings_total"] * 100
        )

    print("## Project Metrics\n")
    print("### Code\n")
    print("| Metric | Value |")
    print("| --- | --- |")
    print(f"| Source files | {metrics['source_files']} |")
    print(f"| Test files | {metrics['test_files']} |")
    print(f"| Test functions | {metrics['test_functions']} |")
    print()
    print("### Findings\n")
    print("| Metric | Value |")
    print("| --- | --- |")
    print(f"| Open | {metrics['findings_open']} |")
    print(f"| Resolved | {metrics['findings_resolved']} |")
    print(f"| Total | {metrics['findings_total']} |")
    print(f"| Resolution rate | {resolution_rate}% |")
    print()
    print("### Project Assets\n")
    print("| Asset | Count |")
    print("| --- | --- |")
    print(f"| Conventions | {metrics['conventions']} |")
    print(f"| Agents | {metrics['agents']} |")
    print(f"| Commands | {metrics['commands']} |")
    print()
    print(
        f"### Compliance ({metrics['compliance_pass']}/{metrics['compliance_total']})\n"
    )
    print("| Check | Status |")
    print("| --- | --- |")
    for check, status in metrics["compliance_details"].items():
        label = check.replace("_", " ").title()
        print(f"| {label} | {status} |")


def save_snapshot(metrics: dict, root: Path) -> Path:
    """Save metrics as JSON snapshot."""
    metrics_dir = root / "reports" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc)
    filename = f"snapshot_{now.strftime('%Y%m%d_%H%M')}.json"
    path = metrics_dir / filename
    path.write_text(json.dumps(metrics, indent=2) + "\n")
    return path


def compare_snapshots(current: dict, snapshot_path: Path) -> None:
    """Compare current metrics against a saved snapshot."""
    previous = json.loads(snapshot_path.read_text())
    print(f"## Metrics Comparison (vs {snapshot_path.name})\n")
    print("| Metric | Previous | Current | Delta |")
    print("| --- | --- | --- | --- |")
    for key in [
        "source_files", "test_files", "test_functions",
        "findings_open", "findings_resolved", "compliance_pass",
    ]:
        prev = previous.get(key, 0)
        curr = current.get(key, 0)
        delta = curr - prev
        sign = "+" if delta > 0 else ""
        label = key.replace("_", " ").title()
        print(f"| {label} | {prev} | {curr} | {sign}{delta} |")


def main() -> None:
    """CLI entry point for project health metrics."""
    parser = argparse.ArgumentParser(description="Project health metrics")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--save", action="store_true", help="Save snapshot")
    parser.add_argument(
        "--compare", type=str, metavar="FILE", help="Compare against snapshot"
    )
    args = parser.parse_args()

    root = find_project_root()
    metrics = collect_metrics(root)

    if args.json:
        print(json.dumps(metrics, indent=2))
    elif args.save:
        path = save_snapshot(metrics, root)
        display_metrics(metrics)
        print(f"\nSnapshot saved to: {path}")
    elif args.compare:
        snapshot_path = Path(args.compare)
        if not snapshot_path.exists():
            print(f"Error: snapshot not found: {args.compare}", file=sys.stderr)
            sys.exit(1)
        compare_snapshots(metrics, snapshot_path)
    else:
        display_metrics(metrics)


if __name__ == "__main__":
    main()
