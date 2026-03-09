#!/usr/bin/env python3
"""Markdown linter and fixer — trailing whitespace, blank lines, language check."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Common French words for language detection
FR_PATTERN = re.compile(
    r"\b(également|c'est|n'est|utilisé|paramètre|créer|supprimé|"
    r"donc|aussi|cette|sont|pour|dans|avec|tous|peut|fait|"
    r"les|des|une|que|qui|sur|pas|ont|ces|aux)\b",
    re.IGNORECASE,
)

# Common Spanish words
ES_PATTERN = re.compile(
    r"\b(también|está|para|como|pero|este|esta|todos|puede|"
    r"cuando|sobre|tiene|desde)\b",
    re.IGNORECASE,
)

# Common German words
DE_PATTERN = re.compile(
    r"\b(auch|diese|wird|nicht|sind|oder|werden|haben|wurde|"
    r"können|zwischen|durch)\b",
    re.IGNORECASE,
)

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".claude"}


def find_project_root() -> Path:
    """Find project root."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / "CLAUDE.md").exists():
            return parent
    return cwd


def should_skip(path: Path) -> bool:
    """Check if path should be skipped."""
    return any(part in SKIP_DIRS for part in path.parts)


def fix_file(path: Path) -> dict:
    """Fix markdown formatting issues in a file. Returns stats."""
    stats = {"trailing_ws": 0, "blank_lines": 0, "final_newline": False}

    content = path.read_text(errors="ignore")
    original = content

    # Fix trailing whitespace (preserve intentional double-space line break)
    lines = content.split("\n")
    fixed_lines = []
    for line in lines:
        stripped = line.rstrip()
        if len(line) != len(stripped):
            if line.endswith("  ") and len(line) - len(stripped) == 2:
                fixed_lines.append(stripped + "  ")
            else:
                fixed_lines.append(stripped)
                stats["trailing_ws"] += 1
        else:
            fixed_lines.append(line)
    content = "\n".join(fixed_lines)

    # Collapse multiple blank lines to one
    while "\n\n\n" in content:
        content = content.replace("\n\n\n", "\n\n")
        stats["blank_lines"] += 1

    # Ensure final newline
    if content and not content.endswith("\n"):
        content += "\n"
        stats["final_newline"] = True

    # Remove trailing blank lines (keep exactly one newline at end)
    content = content.rstrip("\n") + "\n"

    if content != original:
        path.write_text(content)

    return stats


def check_language(path: Path) -> list[str]:
    """Check for non-English content. Returns list of warnings."""
    warnings = []
    content = path.read_text(errors="ignore")

    # Skip code blocks
    content_no_code = re.sub(r"```[\s\S]*?```", "", content)
    # Skip inline code
    content_no_code = re.sub(r"`[^`]+`", "", content_no_code)

    fr_matches = FR_PATTERN.findall(content_no_code)
    if len(fr_matches) >= 3:
        warnings.append(
            f"  Language warning: {path} may contain French "
            f"(found: {', '.join(fr_matches[:5])})"
        )

    es_matches = ES_PATTERN.findall(content_no_code)
    if len(es_matches) >= 3:
        warnings.append(
            f"  Language warning: {path} may contain Spanish "
            f"(found: {', '.join(es_matches[:5])})"
        )

    de_matches = DE_PATTERN.findall(content_no_code)
    if len(de_matches) >= 3:
        warnings.append(
            f"  Language warning: {path} may contain German "
            f"(found: {', '.join(de_matches[:5])})"
        )

    return warnings


def main() -> None:
    """CLI entry point for markdown linting and fixing."""
    parser = argparse.ArgumentParser(description="Fix markdown formatting")
    parser.add_argument("path", nargs="?", help="Scope to specific path")
    parser.add_argument("--check", action="store_true", help="Check only, don't fix")
    args = parser.parse_args()

    root = find_project_root()
    scope = Path(args.path) if args.path else root

    md_files = [scope] if scope.is_file() else [f for f in scope.rglob("*.md") if not should_skip(f)]

    total_fixed = 0
    total_warnings: list[str] = []

    for md in sorted(md_files):
        if args.check:
            content = md.read_text(errors="ignore")
            has_issues = (
                any(line != line.rstrip() for line in content.split("\n"))
                or "\n\n\n" in content
                or (content and not content.endswith("\n"))
            )
            if has_issues:
                print(f"  FIXABLE: {md}")
                total_fixed += 1
        else:
            stats = fix_file(md)
            changes = stats["trailing_ws"] + stats["blank_lines"] + stats["final_newline"]
            if changes:
                print(f"  Fixed: {md} ({changes} issues)")
                total_fixed += 1

        warnings = check_language(md)
        total_warnings.extend(warnings)

    print("\n=== Fix Documentation Summary ===")
    print(f"Files scanned: {len(md_files)}")
    print(f"Files {'with issues' if args.check else 'fixed'}: {total_fixed}")
    print(f"Language warnings: {len(total_warnings)}")

    for w in total_warnings:
        print(w)

    if args.check and total_fixed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
