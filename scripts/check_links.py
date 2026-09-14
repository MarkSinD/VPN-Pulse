"""Check relative Markdown links and images in the repository (offline, no network).

Run: python scripts/check_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


def markdown_files():
    for path in ROOT.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def main() -> int:
    broken: list[str] = []
    checked = 0
    for md in markdown_files():
        text = md.read_text(encoding="utf-8")
        for target in LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            candidate = (md.parent / path_part).resolve()
            checked += 1
            if not candidate.exists():
                broken.append(f"{md.relative_to(ROOT)} -> {target}")
    for item in broken:
        print("broken:", item)
    print(f"links checked: {checked}, broken: {len(broken)}")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
