"""Styling Engine audit: fails (exit 1) on hardcoded Tailwind brand colours.

Tenant branding is injected at runtime as CSS variables, so components must use semantic classes
(`bg-primary`, `text-secondary`, ...) instead of fixed palette classes such as `bg-blue-600`.

Run: ``python3 scripts/find-branding-colors.py`` (wired into ``npm run test:audit``).
"""

import os
import re
import sys

# Resolved relative to this script so the audit works from any working directory.
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src")
SOURCE_SUFFIXES = (".ts", ".tsx")
BRAND_COLOR_PATTERN = re.compile(r"\b(bg|text|border|ring)-(indigo|blue|purple|violet)-[456789]00\b")


def _find_violations() -> list[str]:
    """Returns one `path:line: text` entry per source line that uses a hardcoded brand colour."""
    violations = []
    for root, _, files in os.walk(SRC_DIR):
        for file in files:
            if not file.endswith(SOURCE_SUFFIXES):
                continue
            filepath = os.path.join(root, file)
            with open(filepath, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    if BRAND_COLOR_PATTERN.search(line):
                        violations.append(f"{filepath}:{line_no}: {line.strip()}")
    return violations


def main() -> int:
    """Prints every violation and returns the process exit code (1 when any is found)."""
    violations = _find_violations()
    for violation in violations:
        print(violation)
    print(f"find-branding-colors: {len(violations)} hardcoded brand colour line(s).")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
