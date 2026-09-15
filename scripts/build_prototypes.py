"""Build the self-contained UI prototypes from docs/prototypes/source/.

Inlines the shared tokens, the RU/EN dictionaries (i18n/*.json — the single source of UI
strings) and the demo scenarios (fixtures/ui/scenarios.json — shared with the dev server) into
three standalone HTML files. No secrets, no network.

Run: python scripts/build_prototypes.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "prototypes" / "source"
OUT = ROOT / "docs" / "prototypes"
I18N = ROOT / "i18n"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def minify_json(path: Path) -> str:
    return json.dumps(json.loads(read(path)), ensure_ascii=False, separators=(",", ":"))


def fill(template: str, parts: dict[str, str]) -> str:
    for key, value in parts.items():
        template = template.replace("/*__" + key + "__*/", value)
    return template


def main() -> int:
    i18n = "{" + ",".join(f'"{lang}":{minify_json(I18N / f"{lang}.json")}' for lang in ("ru", "en")) + "}"
    parts = {
        "TOKENS": read(SRC / "ui-tokens.css"),
        "APP_CSS": read(SRC / "app.css"),
        "APP_JS": read(SRC / "app.js"),
        "ANDROID_CSS": read(SRC / "android.css"),
        "ANDROID_JS": read(SRC / "android.js"),
        "ICONS": read(SRC / "icons.svg"),
        "I18N": i18n,
        "FIXTURES": minify_json(ROOT / "fixtures" / "ui" / "scenarios.json"),
    }
    head = (
        '<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="color-scheme" content="light dark">\n'
    )
    (OUT / "ui-tokens.css").write_text(parts["TOKENS"], encoding="utf-8")
    for name in ("mvp", "android", "onboarding"):
        body = fill(read(SRC / f"{name}.src.html"), parts)
        title = re.search(r"<title>(.*?)</title>", body, re.S)
        fragment = body.replace(title.group(0), "", 1) if title else body
        doc = head + (title.group(0) if title else "<title>VPN Pulse</title>") + "\n</head>\n<body>\n" + fragment + "\n</body>\n</html>\n"
        (OUT / f"{name}.html").write_text(doc, encoding="utf-8")
        print(f"built docs/prototypes/{name}.html ({len(doc) // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
