"""Tests for fixdoc.py."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "fixdoc.py"


def test_fixdoc_trailing_whitespace(tmp_path):
    """Fixdoc removes trailing whitespace from markdown files."""
    md = tmp_path / "test.md"
    md.write_text("# Title   \n\nSome text   \n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    content = md.read_text()
    assert "   \n" not in content


def test_fixdoc_multiple_blank_lines(tmp_path):
    """Fixdoc collapses multiple blank lines to one."""
    md = tmp_path / "test.md"
    md.write_text("# Title\n\n\n\n\nText\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    content = md.read_text()
    assert "\n\n\n" not in content


def test_fixdoc_detects_french(tmp_path):
    """Fixdoc warns about non-English content."""
    md = tmp_path / "readme.md"
    md.write_text("# Guide\n\nCette documentation est également en français.\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    assert "language" in result.stdout.lower() or "warning" in result.stdout.lower()


def test_fixdoc_skips_dotdirs(tmp_path):
    """Fixdoc skips .git, .venv directories."""
    dotdir = tmp_path / ".venv" / "lib"
    dotdir.mkdir(parents=True)
    md = dotdir / "test.md"
    md.write_text("# Bad whitespace   \n")

    clean_md = tmp_path / "clean.md"
    clean_md.write_text("# Clean\n")

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    # .venv file should not be touched
    assert md.read_text() == "# Bad whitespace   \n"


def test_fixdoc_ensures_final_newline(tmp_path):
    """Fixdoc ensures files end with exactly one newline."""
    md = tmp_path / "test.md"
    md.write_text("# Title\n\nText")  # No trailing newline

    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0
    content = md.read_text()
    assert content.endswith("\n")
    assert not content.endswith("\n\n")
