"""Tests for findings.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).parent.parent / "findings.py"


def _create_registry(tmp_path: Path, findings: list | None = None) -> Path:
    """Create a minimal findings registry."""
    registry_dir = tmp_path / "reports" / "findings"
    registry_dir.mkdir(parents=True)
    registry = registry_dir / "registry.yml"
    data = {
        "metadata": {"created": "2026-01-01", "last_sync": None},
        "findings": findings or [],
    }
    registry.write_text(yaml.dump(data, default_flow_style=False))
    return registry


def test_findings_show_empty(tmp_path):
    """Show on empty registry prints header with no findings."""
    _create_registry(tmp_path)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "show"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "No open findings" in result.stdout


def test_findings_add(tmp_path):
    """Add creates a new finding with auto-incremented ID."""
    _create_registry(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "add",
            "--severity",
            "HIGH",
            "--title",
            "Missing tests for auth",
            "--file",
            "nautobot_route_tracking/auth.py:10",
            "--category",
            "testing",
            "--description",
            "No test coverage for login flow",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "F-001" in result.stdout

    # Verify registry was updated
    registry = tmp_path / "reports" / "findings" / "registry.yml"
    data = yaml.safe_load(registry.read_text())
    assert len(data["findings"]) == 1
    assert data["findings"][0]["id"] == "F-001"
    assert data["findings"][0]["severity"] == "HIGH"


def test_findings_resolve(tmp_path):
    """Resolve marks a finding as resolved."""
    _create_registry(
        tmp_path,
        findings=[
            {
                "id": "F-001",
                "severity": "HIGH",
                "title": "Bug",
                "file": "x.py:1",
                "status": "open",
                "category": "bugs",
                "description": "A bug",
                "created": "2026-01-01",
                "resolved": None,
                "reason": None,
                "source_audit": "manual",
            },
        ],
    )
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "resolve",
            "F-001",
            "--reason",
            "Fixed in commit abc123",
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "resolved" in result.stdout.lower()

    data = yaml.safe_load((tmp_path / "reports" / "findings" / "registry.yml").read_text())
    assert data["findings"][0]["status"] == "resolved"


def test_findings_stats(tmp_path):
    """Stats displays summary table."""
    _create_registry(
        tmp_path,
        findings=[
            {
                "id": "F-001",
                "severity": "HIGH",
                "title": "Bug",
                "file": "x.py:1",
                "status": "open",
                "category": "bugs",
                "description": "A",
                "created": "2026-01-01",
                "resolved": None,
                "reason": None,
                "source_audit": "manual",
            },
            {
                "id": "F-002",
                "severity": "WARNING",
                "title": "Style",
                "file": "y.py:2",
                "status": "resolved",
                "category": "style",
                "description": "B",
                "created": "2026-01-01",
                "resolved": "2026-01-02",
                "reason": "fixed",
                "source_audit": "manual",
            },
        ],
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "stats"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "Total" in result.stdout
    assert "50%" in result.stdout  # 1/2 resolved
