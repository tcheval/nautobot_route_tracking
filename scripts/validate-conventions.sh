#!/usr/bin/env bash
# validate-conventions.sh
# Checks consistency between _convention/ files and CLAUDE.md
# Exit 0 = all checks pass, Exit 1 = failures found

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

errors=0
warnings=0

echo "=== Convention Validation ==="
echo ""

# Check 1: Required files exist
echo "--- Check 1: Required files ---"
for f in CLAUDE.md _convention/_core.md _convention/README.md; do
    if [ -f "$f" ]; then
        echo -e "  ${GREEN}✓${NC} $f exists"
    else
        echo -e "  ${RED}✗${NC} $f MISSING"
        ((errors++))
    fi
done
echo ""

# Check 2: All convention files have version headers
echo "--- Check 2: Version headers ---"
for f in _convention/_*.md; do
    [ -f "$f" ] || continue
    basename_f=$(basename "$f")
    # Skip template
    [[ "$basename_f" == "_domain-template.md" ]] && continue
    if grep -q '^\*\*Version:\*\*\|^> \*\*Version:\*\*' "$f" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $basename_f has version"
    else
        echo -e "  ${YELLOW}!${NC} $basename_f missing version header"
        ((warnings++))
    fi
done
echo ""

# Check 3: Convention files referenced in CLAUDE.md
echo "--- Check 3: CLAUDE.md references ---"
convention_files=$(find _convention -name '*.md' -not -name 'README.md' -not -name '_domain-template.md' | sort)
for f in $convention_files; do
    basename_f=$(basename "$f")
    if grep -q "$basename_f\|${f}" CLAUDE.md 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $basename_f referenced in CLAUDE.md"
    else
        echo -e "  ${YELLOW}!${NC} $basename_f NOT referenced in CLAUDE.md"
        ((warnings++))
    fi
done
echo ""

# Check 4: Convention files listed in _convention/README.md
echo "--- Check 4: README.md table ---"
for f in $convention_files; do
    basename_f=$(basename "$f")
    if grep -q "$basename_f" _convention/README.md 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $basename_f listed in _convention/README.md"
    else
        echo -e "  ${YELLOW}!${NC} $basename_f NOT listed in _convention/README.md"
        ((warnings++))
    fi
done
echo ""

# Check 5: Cross-references between convention files resolve
echo "--- Check 5: Cross-references ---"
refs_total=0
refs_valid=0
for f in _convention/*.md; do
    [ -f "$f" ] || continue
    # Extract references to other convention files
    grep -oE '_convention/[a-zA-Z0-9_-]+\.md' "$f" 2>/dev/null | sort -u | while read -r ref; do
        ((refs_total++)) || true
        if [ -f "$ref" ]; then
            echo -e "  ${GREEN}✓${NC} $(basename "$f") → $ref"
            ((refs_valid++)) || true
        else
            echo -e "  ${RED}✗${NC} $(basename "$f") → $ref BROKEN"
            ((errors++))
        fi
    done
done
echo ""

# Check 6: No ../  paths in convention files
echo "--- Check 6: Root-relative paths ---"
dotdot_count=$(grep -r '\.\.\/' _convention/ 2>/dev/null | wc -l | tr -d ' ')
if [ "$dotdot_count" -eq 0 ]; then
    echo -e "  ${GREEN}✓${NC} No ../ paths found"
else
    echo -e "  ${RED}✗${NC} Found $dotdot_count lines with ../ paths"
    grep -rn '\.\.\/' _convention/ 2>/dev/null | head -5
    ((errors++))
fi
echo ""

# Summary
echo "=== Results ==="
echo -e "  Errors:   ${errors}"
echo -e "  Warnings: ${warnings}"
echo ""

if [ "$errors" -gt 0 ]; then
    echo -e "${RED}FAIL${NC} — $errors error(s) found"
    exit 1
elif [ "$warnings" -gt 0 ]; then
    echo -e "${YELLOW}PASS with warnings${NC} — $warnings warning(s)"
    exit 0
else
    echo -e "${GREEN}PASS${NC} — all checks passed"
    exit 0
fi
