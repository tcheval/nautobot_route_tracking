"""Tests for metrics.py."""

import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "metrics.py"


def test_metrics_display(tmp_path, monkeypatch):
    """metrics.py with no args prints markdown output."""
    monkeypatch.chdir(tmp_path)
    # Minimal project structure
    (tmp_path / "CLAUDE.md").write_text("# Test")
    (tmp_path / "_convention").mkdir()
    (tmp_path / "_convention" / "_core.md").write_text("# Core")
    (tmp_path / "nautobot_route_tracking").mkdir()
    (tmp_path / "nautobot_route_tracking" / "models.py").write_text("class RouteEntry:\n    pass\n")
    (tmp_path / "nautobot_route_tracking" / "jobs").mkdir()
    (tmp_path / "nautobot_route_tracking" / "jobs" / "__init__.py").write_text(
        "from nautobot.core.celery import register_jobs\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_models.py").write_text("def test_main():\n    assert True\n")
    (tmp_path / "reports" / "findings").mkdir(parents=True)
    (tmp_path / "reports" / "findings" / "registry.yml").write_text(
        "metadata:\n  created: '2026-01-01'\n  last_sync: null\nfindings: []\n"
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "Project Metrics" in result.stdout
    assert "Source files" in result.stdout


def test_metrics_json(tmp_path, monkeypatch):
    """metrics.py --json outputs valid JSON."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# Test")
    (tmp_path / "_convention").mkdir()
    (tmp_path / "_convention" / "_core.md").write_text("# Core")
    (tmp_path / "nautobot_route_tracking").mkdir()
    (tmp_path / "nautobot_route_tracking" / "jobs").mkdir()
    (tmp_path / "nautobot_route_tracking" / "jobs" / "__init__.py").write_text(
        "from nautobot.core.celery import register_jobs\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "reports" / "findings").mkdir(parents=True)
    (tmp_path / "reports" / "findings" / "registry.yml").write_text(
        "metadata:\n  created: '2026-01-01'\n  last_sync: null\nfindings: []\n"
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert "source_files" in data
    assert "test_files" in data
    assert "findings_open" in data


def test_metrics_save(tmp_path, monkeypatch):
    """metrics.py --save creates a snapshot file."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# Test")
    (tmp_path / "_convention").mkdir()
    (tmp_path / "_convention" / "_core.md").write_text("# Core")
    (tmp_path / "nautobot_route_tracking").mkdir()
    (tmp_path / "nautobot_route_tracking" / "jobs").mkdir()
    (tmp_path / "nautobot_route_tracking" / "jobs" / "__init__.py").write_text(
        "from nautobot.core.celery import register_jobs\n"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "reports" / "findings").mkdir(parents=True)
    (tmp_path / "reports" / "findings" / "registry.yml").write_text(
        "metadata:\n  created: '2026-01-01'\n  last_sync: null\nfindings: []\n"
    )
    (tmp_path / "reports" / "metrics").mkdir(parents=True)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--save"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    snapshots = list((tmp_path / "reports" / "metrics").glob("snapshot_*.json"))
    assert len(snapshots) == 1
