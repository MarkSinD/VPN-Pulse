"""Parity check: the Mini App renders the same DOM from the API as from the demo scenarios.

For every scenario × role × language × screen the page is opened twice — once as a file with the
inlined scenarios (`?data=fixtures`) and once from the dev server (`/app/…`, live API) — and the
rendered header, content and navigation are compared character by character. Any drift between
`web/src/model.js` producers, the dev server presenter or the contract shows up here as a named
mismatch. The dev server is started for the duration of the run.

Run: python scripts/ui_parity_check.py            (needs playwright + chromium, uvicorn)
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
MVP_FILE = (ROOT / "docs" / "prototypes" / "mvp.html").as_uri()
sys.path.insert(0, str(ROOT / "src"))
from vpnpulse.dev.scenarios import ScenarioCatalog  # noqa: E402

CATALOG = ScenarioCatalog.load(ROOT / "fixtures" / "ui" / "scenarios.json")
SCENARIOS = [s for s in CATALOG.ids if CATALOG.merged(s).get("api") != "offline"]
SCREENS = ["status", "events", "help", "keys", "admin", "server:s1", "server:s2", "server:s3"]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> subprocess.Popen:
    proc = subprocess.Popen([sys.executable, "-m", "vpnpulse.dev", "--port", str(port)], cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")})
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health/live", timeout=1)
            return proc
        except Exception:
            time.sleep(0.2)
    proc.kill()
    raise SystemExit("dev server did not start")


NORMALIZE = re.compile(r"\s+")


def snapshot(pg) -> str:
    html = pg.evaluate("() => ['app-header','app-scroll','app-nav'].map(id => document.getElementById(id).innerHTML).join('\\n<!-- ~ -->\\n')")
    return NORMALIZE.sub(" ", html).strip()


def first_diff(a: str, b: str) -> str:
    i = next((k for k, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
    return f"@{i}: fixtures «{a[max(0, i - 80):i + 120]}» | api «{b[max(0, i - 80):i + 120]}»"


def main() -> int:
    port = free_port()
    server = start_server(port)
    compared = 0
    mismatches: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for scenario in SCENARIOS:
                for role in ("member", "admin"):
                    for lang in ("ru", "en"):
                        ctx = browser.new_context(viewport={"width": 390, "height": 844}, timezone_id="UTC", locale="ru-RU" if lang == "ru" else "en-GB")
                        fx, api = ctx.new_page(), ctx.new_page()
                        common = f"scenario={scenario}&role={role}&lang={lang}&showcase=hidden&theme=light"
                        fx.goto(f"{MVP_FILE}?data=fixtures&{common}")
                        api.goto(f"http://127.0.0.1:{port}/app/mvp.html?{common}")
                        for pg in (fx, api):
                            pg.wait_for_selector('body[data-load="ready"]', timeout=15000)
                        has_servers = fx.evaluate("() => document.querySelectorAll('.srow[data-server]').length")
                        for screen in SCREENS:
                            if screen == "admin" and role != "admin":
                                continue
                            if screen.startswith("server:") and not has_servers:
                                continue
                            for pg in (fx, api):
                                pg.evaluate("s => window.VPNPulseShowcase.apply({ screen: s })", screen)
                            a, b = snapshot(fx), snapshot(api)
                            compared += 1
                            if a != b:
                                mismatches.append(f"{scenario} / {role} / {lang} / {screen}: {first_diff(a, b)}")
                        ctx.close()
            # offline: the API answers 503 and the app shows the offline banner with a retry
            ctx = browser.new_context(viewport={"width": 390, "height": 844}, timezone_id="UTC")
            pg = ctx.new_page()
            pg.goto(f"http://127.0.0.1:{port}/app/mvp.html?scenario=offline&showcase=hidden")
            pg.wait_for_selector('body[data-load="ready"]', timeout=15000)
            compared += 1
            if pg.locator(".banner-warn [data-retry]").count() != 1:
                mismatches.append("offline / api: retry banner missing")
            ctx.close()
            browser.close()
    finally:
        server.terminate()
    print(f"parity: {compared} screen comparisons across {len(SCENARIOS)} scenarios, mismatches: {len(mismatches)}")
    for m in mismatches[:40]:
        print(" -", m)
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
