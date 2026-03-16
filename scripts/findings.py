#!/usr/bin/env python3
"""Findings registry manager — show, add, resolve, stats, sync."""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import yaml

REGISTRY_PATH = Path("reports/findings/registry.yml")


def load_registry(root: Path) -> dict:
    """Load findings registry."""
    path = root / REGISTRY_PATH
    if not path.exists():
        return {"metadata": {"created": str(date.today()), "last_sync": None}, "findings": []}
    return yaml.safe_load(path.read_text()) or {"metadata": {}, "findings": []}


def save_registry(root: Path, data: dict) -> None:
    """Save findings registry."""
    path = root / REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))


def next_id(findings: list) -> str:
    """Generate next finding ID (F-001, F-002, ...)."""
    if not findings:
        return "F-001"
    max_num = 0
    for f in findings:
        fid = f.get("id", "F-000")
        try:
            num = int(fid.split("-")[1])
            max_num = max(max_num, num)
        except (IndexError, ValueError):
            pass
    return f"F-{max_num + 1:03d}"


def find_project_root() -> Path:
    """Find project root."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "CLAUDE.md").exists():
            return parent
    return cwd


def cmd_show(args: argparse.Namespace, root: Path) -> None:
    """Display findings."""
    data = load_registry(root)
    findings = data.get("findings") or []

    status_filter = getattr(args, "status", "open")
    severity_filter = getattr(args, "severity", None)
    show_all = getattr(args, "all", False)

    if not show_all:
        findings = [f for f in findings if f.get("status") == status_filter]
    if severity_filter:
        findings = [f for f in findings if f.get("severity") == severity_filter]

    if not findings:
        print("No open findings." if not show_all else "No findings found.")
        return

    severity_order = {"CRITICAL": 0, "HIGH": 1, "WARNING": 2, "INFO": 3}
    findings.sort(key=lambda f: severity_order.get(f.get("severity", "INFO"), 9))

    print("| ID | Severity | Category | Title | Status |")
    print("| --- | --- | --- | --- | --- |")
    for f in findings:
        print(
            f"| {f['id']} | {f.get('severity', '-')} | {f.get('category', '-')} "
            f"| {f.get('title', '-')} | {f.get('status', '-')} |"
        )
    print(f"\nTotal: {len(findings)} findings")


def cmd_add(args: argparse.Namespace, root: Path) -> None:
    """Add a new finding."""
    data = load_registry(root)
    findings = data.get("findings") or []

    fid = next_id(findings)
    finding = {
        "id": fid,
        "severity": args.severity,
        "category": args.category or "general",
        "title": args.title,
        "description": args.description or "",
        "file": args.file or "",
        "status": "open",
        "created": str(date.today()),
        "resolved": None,
        "reason": None,
        "source_audit": "manual",
    }
    findings.append(finding)
    data["findings"] = findings
    save_registry(root, data)
    print(f"Added finding {fid}: {args.title}")


def cmd_resolve(args: argparse.Namespace, root: Path) -> None:
    """Resolve a finding."""
    data = load_registry(root)
    findings = data.get("findings") or []

    finding_id = args.finding_id
    for f in findings:
        if f["id"] == finding_id:
            f["status"] = "resolved"
            f["resolved"] = str(date.today())
            f["reason"] = args.reason or "resolved"
            save_registry(root, data)
            print(f"Resolved {finding_id}: {f['title']}")
            return

    print(f"Error: finding {finding_id} not found", file=sys.stderr)
    sys.exit(1)


def cmd_stats(args: argparse.Namespace, root: Path) -> None:
    """Display summary statistics."""
    data = load_registry(root)
    findings = data.get("findings") or []

    total = len(findings)
    open_count = sum(1 for f in findings if f.get("status") == "open")
    resolved = sum(1 for f in findings if f.get("status") == "resolved")
    rate = round(resolved / total * 100) if total > 0 else 0

    print("## Findings Summary\n")
    print("| Metric | Value |")
    print("| --- | --- |")
    print(f"| Total | {total} |")
    print(f"| Open | {open_count} |")
    print(f"| Resolved | {resolved} |")
    print(f"| Resolution rate | {rate}% |")

    open_findings = [f for f in findings if f.get("status") == "open"]
    if open_findings:
        print("\n## Open by Severity\n")
        print("| Severity | Count |")
        print("| --- | --- |")
        for sev in ["CRITICAL", "HIGH", "WARNING", "INFO"]:
            count = sum(1 for f in open_findings if f.get("severity") == sev)
            if count > 0:
                print(f"| {sev} | {count} |")


def cmd_sync(args: argparse.Namespace, root: Path) -> None:
    """Sync findings from audit reports."""
    data = load_registry(root)
    findings = data.get("findings") or []
    existing_titles = {f.get("title", "").lower() for f in findings}

    audit_dir = root / "reports" / "audit"
    if not audit_dir.exists():
        print("No audit reports found in reports/audit/")
        return

    audit_files = sorted(audit_dir.glob("audit_*.md"))
    if not audit_files:
        print("No audit reports found.")
        return

    added = 0
    for audit_file in audit_files:
        content = audit_file.read_text(errors="ignore")
        rows = re.findall(
            r"\|\s*(CRITICAL|HIGH|WARNING|INFO)\s*\|([^|]+)\|([^|]+)\|([^|]*)\|",
            content,
        )
        for severity, area, issue, fix in rows:
            title = issue.strip()
            if title.lower() in existing_titles:
                continue
            fid = next_id(findings)
            finding = {
                "id": fid,
                "severity": severity.strip(),
                "category": area.strip(),
                "title": title,
                "description": fix.strip() if fix.strip() else "",
                "file": "",
                "status": "open",
                "created": str(date.today()),
                "resolved": None,
                "reason": None,
                "source_audit": audit_file.name,
            }
            findings.append(finding)
            existing_titles.add(title.lower())
            added += 1

    data["findings"] = findings
    data["metadata"]["last_sync"] = str(date.today())
    save_registry(root, data)
    print(f"Synced {len(audit_files)} audit files. Added {added} new findings.")


def main() -> None:
    """CLI entry point for findings registry management."""
    parser = argparse.ArgumentParser(description="Findings registry manager")
    subparsers = parser.add_subparsers(dest="command", required=True)

    show_parser = subparsers.add_parser("show", help="Display findings")
    show_parser.add_argument("--severity", help="Filter by severity")
    show_parser.add_argument("--status", default="open", help="Filter by status")
    show_parser.add_argument("--all", action="store_true", help="Show all findings")

    add_parser = subparsers.add_parser("add", help="Add a new finding")
    add_parser.add_argument("--severity", required=True, help="CRITICAL|HIGH|WARNING|INFO")
    add_parser.add_argument("--title", required=True, help="Finding title")
    add_parser.add_argument("--file", help="File path and line")
    add_parser.add_argument("--category", help="Category name")
    add_parser.add_argument("--description", help="Detailed description")

    resolve_parser = subparsers.add_parser("resolve", help="Resolve a finding")
    resolve_parser.add_argument("finding_id", help="Finding ID (e.g., F-001)")
    resolve_parser.add_argument("--reason", help="Resolution description")

    subparsers.add_parser("stats", help="Display summary statistics")
    subparsers.add_parser("sync", help="Sync from audit reports")

    args = parser.parse_args()
    root = find_project_root()

    commands = {
        "show": cmd_show,
        "add": cmd_add,
        "resolve": cmd_resolve,
        "stats": cmd_stats,
        "sync": cmd_sync,
    }
    commands[args.command](args, root)


if __name__ == "__main__":
    main()
