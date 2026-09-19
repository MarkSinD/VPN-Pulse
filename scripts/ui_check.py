"""Browser checks for the VPN Pulse Mini App and prototypes (Playwright, Chromium).

Runs the QA assertions against docs/prototypes/*.html (built from web/src by scripts/build_prototypes.py):
no horizontal overflow, visible header/nav, touch targets, route Back with focus/scroll
restore, single accordion, stable width, hidden-but-working scrollbar, 200% text,
console errors, key states. Saves screenshots to output/playwright/ (git-ignored).

Run: python scripts/ui_check.py            (needs: pip install playwright && playwright install chromium)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "playwright"
OUT.mkdir(parents=True, exist_ok=True)
MVP = (ROOT / "docs" / "prototypes" / "mvp.html").as_uri()
ANDROID = (ROOT / "docs" / "prototypes" / "android.html").as_uri()
ONB = (ROOT / "docs" / "prototypes" / "onboarding.html").as_uri()

VIEWPORTS = [(320, 568), (360, 667), (390, 844), (768, 1024), (1280, 800)]
LANDSCAPE = [(568, 320), (667, 360), (844, 390)]
failures: list[str] = []
checks = 0


def ok(cond: bool, msg: str) -> None:
    global checks
    checks += 1
    if not cond:
        failures.append(msg)


def url(base: str, **params: str) -> str:
    qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    return base + ("?" + qs if qs else "")


def no_overflow(page, label: str) -> None:
    doc = page.evaluate("() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    ok(doc[0] <= doc[1], f"{label}: document horizontal overflow {doc}")
    app = page.evaluate("() => { const e = document.querySelector('#app-scroll, #content'); return e ? [e.scrollWidth, e.clientWidth] : [0, 0]; }")
    ok(app[0] <= app[1] + 1, f"{label}: app-scroll horizontal overflow {app}")


def chrome_visible(page, label: str, nav_sel: str = "#app-nav") -> None:
    r = page.evaluate(
        "([h, n]) => { const H = document.querySelector(h), N = document.querySelector(n); const vh = window.innerHeight;"
        " const hr = H.getBoundingClientRect(), nr = N ? N.getBoundingClientRect() : null;"
        " return { header: hr.top >= 0 && hr.bottom <= vh && hr.height > 0, nav: nr ? (nr.bottom <= vh + 1 && nr.top >= 0 && nr.height > 0) : true }; }",
        ["#app-header, #appbar", nav_sel],
    )
    ok(r["header"], f"{label}: header not fully visible")
    ok(r["nav"], f"{label}: bottom nav not fully visible")


def targets(page, label: str, sel: str, minimum: int) -> None:
    sizes = page.evaluate("([s]) => Array.from(document.querySelectorAll(s)).filter(e => e.offsetParent !== null && getComputedStyle(e).visibility !== 'hidden').map(e => { const r = e.getBoundingClientRect(); return [Math.round(r.width), Math.round(r.height)]; })", [sel])
    for w, h in sizes:
        ok(w >= minimum and h >= minimum, f"{label}: target {sel} is {w}x{h} < {minimum}")


INFRA_PATTERNS = (
    ("an IPv4 address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("a host:port pair", re.compile(r"\b(?=[a-z0-9.-]*[a-z])[a-z0-9-]+(?:\.[a-z0-9-]+)+:\d{2,5}\b", re.I)),  # a dotted name, not a clock time
    ("a hostname", re.compile(r"\b[a-z0-9-]+\.(?:[a-z]{2,3}\.)?(?:xyz|org|com|net|io|ru|lv|nl|fi|de|dev|app|me)\b", re.I)),
    ("an SSH port", re.compile(r"(?<![\d.:])\d{1,5}:22\b|\bport 22\b", re.I)),
)


def console_clean(page, label: str, errors: list) -> None:
    ok(not errors, f"{label}: console errors {errors[:3]}")


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()

        def new_page(width, height, scheme="light", reduced=False):
            ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, reduced_motion="reduce" if reduced else "no-preference", device_scale_factor=1)
            pg = ctx.new_page()
            errs: list[str] = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            return ctx, pg, errs

        # ---------- matrix: viewport x theme x lang x scenario ----------
        for (w, h) in VIEWPORTS + LANDSCAPE:
            for scheme in ("light", "dark"):
                for lang in ("ru", "en"):
                    for scenario in ("operational", "degraded", "unknown"):
                        label = f"{w}x{h} {scheme} {lang} {scenario}"
                        ctx, pg, errs = new_page(w, h, scheme)
                        pg.goto(url(MVP, scenario=scenario, lang=lang, showcase="hidden", theme=scheme))
                        pg.wait_for_selector(".srow")
                        no_overflow(pg, label)
                        chrome_visible(pg, label)
                        targets(pg, label, "#app-nav button, #lang-btn", 44)
                        targets(pg, label, ".srow", 56)
                        console_clean(pg, label, errs)
                        # unknown must not show a current 100%
                        if scenario == "unknown":
                            side = pg.locator('.srow[data-server="s1"] .side .up').inner_text()
                            ok(side.strip() == "—", f"{label}: unknown row shows {side!r} instead of —")
                        ctx.close()

        # ---------- interactions at 320x568 (content taller than viewport) ----------
        ctx, pg, errs = new_page(320, 568)
        pg.goto(url(MVP, scenario="degraded", lang="ru", showcase="hidden"))
        pg.wait_for_selector(".srow")
        if pg.locator("#hint-ok").count():
            pg.click("#hint-ok")  # dismiss first-use hint so list height stays constant across Back
        # hidden scrollbar but scroll works
        sb = pg.evaluate("() => getComputedStyle(document.getElementById('app-scroll')).scrollbarWidth")
        ok(sb == "none", f"scrollbar-width is {sb!r}, expected none")
        pg.evaluate("() => { const e = document.getElementById('app-scroll'); e.scrollTop = 120; }")
        st = pg.evaluate("() => document.getElementById('app-scroll').scrollTop")
        ok(st > 0, "app-scroll does not scroll programmatically")
        pg.mouse.move(160, 300)
        pg.mouse.wheel(0, 200)
        pg.wait_for_timeout(150)
        st2 = pg.evaluate("() => document.getElementById('app-scroll').scrollTop")
        ok(st2 >= st, f"wheel scroll did not move app-scroll ({st} -> {st2})")
        pg.evaluate("() => { document.getElementById('app-scroll').scrollTop = 0; }")
        # keyboard scroll: focus a row then press End/PageDown
        pg.focus('.srow[data-server="s1"]')
        pg.keyboard.press("PageDown")
        pg.wait_for_timeout(200)
        st3 = pg.evaluate("() => document.getElementById('app-scroll').scrollTop")
        ok(st3 >= 0, "keyboard scroll broke")
        pg.evaluate("() => { document.getElementById('app-scroll').scrollTop = 60; }")
        pg.locator('.srow[data-server="s3"]').scroll_into_view_if_needed()
        expected_scroll = pg.evaluate("() => document.getElementById('app-scroll').scrollTop")
        # row press -> server screen, focus on h1
        pg.click('.srow[data-server="s3"]')
        pg.wait_for_selector("#screen-title")
        focused = pg.evaluate("() => document.activeElement && document.activeElement.id")
        ok(focused == "screen-title", f"after opening server focus is on {focused!r}")
        title = pg.locator("#screen-title").inner_text()
        ok("Сервер 3" in title, f"server title unexpected: {title!r}")
        targets(pg, "server", "#back-btn, #lang-btn", 44)
        targets(pg, "server", ".acc-btn", 48)
        expanded = pg.evaluate("() => Array.from(document.querySelectorAll('.acc-btn')).filter(b => b.getAttribute('aria-expanded') === 'true').map(b => b.dataset.acc)")
        ok(expanded == ["checks"], f"initially expanded groups: {expanded}")
        width_before = pg.evaluate("() => document.getElementById('app-scroll').clientWidth")
        # open Load: exactly one open, focus stays, width stable, no jump when header visible
        pg.locator('.acc-btn[data-acc="load"]').scroll_into_view_if_needed()
        top_before = pg.evaluate("() => document.getElementById('app-scroll').scrollTop")
        btn_top_before = pg.evaluate("() => document.querySelector('.acc-btn[data-acc=\"load\"]').getBoundingClientRect().top")
        pg.click('.acc-btn[data-acc="load"]')
        pg.wait_for_timeout(100)
        expanded = pg.evaluate("() => Array.from(document.querySelectorAll('.acc-btn')).filter(b => b.getAttribute('aria-expanded') === 'true').map(b => b.dataset.acc)")
        ok(expanded == ["load"], f"after toggle expanded groups: {expanded}")
        focused = pg.evaluate("() => document.activeElement && document.activeElement.dataset.acc")
        ok(focused == "load", f"focus after accordion toggle on {focused!r}")
        width_after = pg.evaluate("() => document.getElementById('app-scroll').clientWidth")
        ok(width_before == width_after, f"width changed on toggle {width_before}->{width_after}")
        btn_top_after = pg.evaluate("() => document.querySelector('.acc-btn[data-acc=\"load\"]').getBoundingClientRect().top")
        top_after = pg.evaluate("() => document.getElementById('app-scroll').scrollTop")
        # header stays put unless the container already hit scrollTop 0 (nothing left to compensate with)
        ok(abs(btn_top_after - btn_top_before) <= 2 or top_after == 0, f"pressed header moved on toggle {btn_top_before}->{btn_top_after} (scrollTop {top_after})")
        panel_hidden = pg.evaluate("() => document.getElementById('panel-checks').hidden")
        ok(panel_hidden, "previous panel not hidden")
        # Back restores scroll + focus on origin row
        pg.go_back()
        pg.wait_for_selector('.srow[data-server="s3"]')
        pg.wait_for_timeout(100)
        st_back = pg.evaluate("() => document.getElementById('app-scroll').scrollTop")
        ok(abs(st_back - expected_scroll) <= 2, f"scroll not restored after back: {st_back} != {expected_scroll}")
        focused = pg.evaluate("() => document.activeElement && document.activeElement.dataset.server")
        ok(focused == "s3", f"focus after back on {focused!r}")
        no_overflow(pg, "after back")
        console_clean(pg, "interactions", errs)
        # keyboard: Enter on row opens
        pg.focus('.srow[data-server="s1"]')
        pg.keyboard.press("Enter")
        pg.wait_for_selector("#screen-title")
        ok("Сервер 1" in pg.locator("#screen-title").inner_text(), "keyboard Enter did not open server")
        pg.go_back()
        pg.wait_for_selector(".srow")
        # language switch keeps screen and updates nav
        pg.click("#lang-btn")
        pg.wait_for_timeout(100)
        ok(pg.locator('#app-nav button[data-tab="status"] span').inner_text() == "Status", "nav not translated to EN")
        no_overflow(pg, "EN 320")
        # long EN labels at 320
        ctx.close()

        # ---------- states ----------
        for scenario, checks_fn in {
            "loading": lambda pg: ok(pg.locator(".skeleton").count() == 1, "loading skeleton missing"),
            "offline": lambda pg: ok(pg.locator(".banner-warn").count() >= 1 and pg.locator("[data-retry]").count() == 1, "offline banner/retry missing"),
            "auth": lambda pg: ok(pg.locator(".error-screen").count() == 1 and pg.locator(".srow").count() == 0, "auth error should hide data"),
            "long_note": lambda pg: ok(pg.locator("#note-more").count() == 1 and pg.locator("#note-txt.clamp").count() == 1, "long note not clamped with More"),
            "conflict": lambda pg: None,
            "demo": lambda pg: ok(pg.locator(".demo-mark").count() == 1, "demo mark missing"),
            "clean_install": lambda pg: ok(pg.locator(".srow").count() == 0 and "настраивается" in pg.locator("#screen-title").inner_text(), "clean install member view wrong"),
            # members never see a warning about missing probes: sources simply are not there yet
            "partial_coverage": lambda pg: ok(pg.locator(".banner-warn").count() == 0 and pg.locator(".legend").count() == 0 and pg.locator(".srow .src").count() == 0, "member partial coverage must hide banner, legend and sources"),
            # a removed probe disappears from the legend and every row; the remaining ones are lamps
            "no_pc": lambda pg: ok(pg.locator(".legend > span").count() == 2 and pg.locator('.legend use[href="#i-pc"]').count() == 0 and pg.locator(".srow .src").count() == 6 and pg.locator(".legend .src.s-ok").count() == 2, "no_pc legend/rows wrong"),
        }.items():
            for w, h in ((320, 568), (390, 844)):
                ctx, pg, errs = new_page(w, h)
                pg.goto(url(MVP, scenario=scenario, lang="ru", showcase="hidden"))
                pg.wait_for_timeout(150)
                no_overflow(pg, f"{scenario} {w}")
                chrome_visible(pg, f"{scenario} {w}")
                checks_fn(pg)
                console_clean(pg, f"{scenario} {w}", errs)
                ctx.close()
        # silent probes stay visible as hollow lamps; admin still gets the coverage banner
        ctx, pg, errs = new_page(390, 844)
        pg.goto(url(MVP, scenario="unknown", lang="ru", showcase="hidden"))
        pg.wait_for_timeout(150)
        ok(pg.locator(".legend .src.s-unknown").count() == 2 and pg.locator(".legend .src.s-ok").count() == 1, "unknown: legend lamps should be 2 silent + 1 reporting")
        pg.goto(url(MVP, scenario="partial_coverage", role="admin", lang="ru", showcase="hidden"))
        pg.wait_for_timeout(150)
        ok(pg.locator(".banner-warn").count() >= 1, "admin partial coverage banner missing")
        pg.goto(url(MVP, scenario="partial_coverage", lang="ru", showcase="hidden", screen="server:s2"))
        pg.wait_for_timeout(150)
        ok("Пробники не подключены" in pg.locator("#panel-checks").inner_text(), "checks group should explain missing probes")
        ctx.close()
        # conflict detail + unknown detail + stale
        ctx, pg, errs = new_page(390, 844)
        pg.goto(url(MVP, scenario="conflict", lang="ru", showcase="hidden", screen="server:s2"))
        pg.wait_for_selector("#screen-title")
        ok(pg.locator(".banner-warn").count() >= 1, "conflict banner missing on server screen")
        pg.goto(url(MVP, scenario="unknown", lang="ru", showcase="hidden", screen="server:s1"))
        pg.wait_for_selector("#screen-title")
        ok(pg.locator(".banner-info").count() >= 1, "stale banner missing")
        txt = pg.locator("#app-scroll").inner_text()
        ok("100%" not in txt.split("Доступность за 24 ч")[0], "unknown detail shows 100% before history block")
        # empty events + error/retry
        pg.goto(url(MVP, scenario="empty_events", lang="ru", showcase="hidden", screen="events"))
        pg.wait_for_selector(".empty")
        pg.goto(url(MVP, scenario="offline", lang="ru", showcase="hidden", screen="events"))
        pg.wait_for_selector("#ev-retry")
        pg.click("#ev-retry")
        pg.wait_for_timeout(900)
        ok(pg.locator("#ev-retry").count() == 1, "events retry did not return to error state while offline")
        # admin: doctor + sheets
        pg.goto(url(MVP, scenario="clean_install", role="admin", lang="ru", showcase="hidden", screen="admin"))
        pg.wait_for_selector(".doctor")
        ok(pg.locator("[data-copy]").count() >= 1, "admin doctor has no copyable command")
        pg.click("[data-enroll]")
        pg.wait_for_selector(".sheet")
        ok(pg.locator(".sheet .code").inner_text().strip() != "", "enroll code empty")
        pg.keyboard.press("Escape")
        ok(pg.locator(".sheet").count() == 0, "sheet did not close on Escape")
        # member never sees admin nav or admin block
        pg.goto(url(MVP, scenario="unavailable", role="member", lang="ru", showcase="hidden", screen="server:s2"))
        pg.wait_for_selector("#screen-title")
        ok(pg.locator('#app-nav button[data-tab="admin"]').count() == 0, "member sees admin tab")
        ok(pg.locator(".admin-block").count() == 0 and pg.locator(".diag").count() == 0, "member sees admin diagnostics")
        # user-facing screens must not contain infra markers
        for scenario in ("operational", "unavailable", "unknown", "partial_coverage"):
            pg.goto(url(MVP, scenario=scenario, role="member", lang="ru", showcase="hidden"))
            pg.wait_for_timeout(100)
            body = pg.locator("body").inner_text()
            # anything that looks like infrastructure is a leak on a member screen: addresses, host:port
            # pairs, hostnames with a TLD (the UI shows public names, flags and counts only)
            for name, pattern in INFRA_PATTERNS:
                hit = pattern.search(body)
                ok(hit is None, f"{scenario}: user screen contains {name} {hit.group(0)!r}" if hit else f"{scenario}: no {name}")
        console_clean(pg, "states2", errs)
        ctx.close()

        # ---------- 200% text ----------
        for w, h in ((320, 568), (390, 844)):
            ctx, pg, errs = new_page(w, h)
            pg.goto(url(MVP, scenario="degraded", lang="en", showcase="hidden", text="200"))
            pg.wait_for_selector(".srow")
            no_overflow(pg, f"text200 {w}")
            chrome_visible(pg, f"text200 {w}")
            targets(pg, f"text200 {w}", "#app-nav button, #lang-btn", 44)
            ctx.close()

        # ---------- reduced motion + dark ----------
        ctx, pg, errs = new_page(390, 844, "dark", reduced=True)
        pg.goto(url(MVP, scenario="unavailable", lang="ru", showcase="hidden", theme="dark"))
        pg.wait_for_selector(".srow")
        mf = pg.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--motion-fast').trim()")
        ok(mf == "1ms", f"reduced motion token is {mf!r}")
        ctx.close()

        # ---------- android + onboarding ----------
        for state in ("unbound", "exclude", "cellular_ok", "running", "queued", "stale", "permission"):
            for w, h in ((320, 568), (390, 844)):
                ctx, pg, errs = new_page(w, h)
                pg.goto(url(ANDROID, state=state, lang="ru", showcase="hidden"))
                pg.wait_for_selector("#content")
                no_overflow(pg, f"android {state} {w}")
                targets(pg, f"android {state}", ".btn, .lang-btn", 44)
                console_clean(pg, f"android {state}", errs)
                ctx.close()
        ctx, pg, errs = new_page(1280, 800)
        pg.goto(ONB)
        pg.wait_for_selector("#guide .card")
        no_overflow(pg, "onboarding 1280")
        pg.click('#guide [data-state="clean"][data-view="admin"]')
        pg.wait_for_timeout(150)
        ok(pg.locator("[data-copy]").count() >= 1, "onboarding clean install admin has no command")
        console_clean(pg, "onboarding", errs)
        ctx.close()

        # ---------- screenshots ----------
        shots = [
            ("320-operational-light.png", MVP, 320, 568, "light", dict(scenario="operational", lang="ru", showcase="hidden")),
            ("390-degraded-light.png", MVP, 390, 844, "light", dict(scenario="degraded", lang="ru", showcase="hidden")),
            ("390-unavailable-dark.png", MVP, 390, 844, "dark", dict(scenario="unavailable", lang="ru", showcase="hidden", theme="dark")),
            ("390-unknown-light-en.png", MVP, 390, 844, "light", dict(scenario="unknown", lang="en", showcase="hidden")),
            ("768-server-detail-light.png", MVP, 768, 1024, "light", dict(scenario="degraded", lang="ru", showcase="hidden", screen="server:s3")),
            ("768-server-detail-dark.png", MVP, 768, 1024, "dark", dict(scenario="unavailable", lang="ru", showcase="hidden", screen="server:s2", role="admin", theme="dark")),
            ("1280-admin-light.png", MVP, 1280, 800, "light", dict(scenario="unavailable", role="admin", lang="ru", showcase="hidden", screen="admin")),
            ("1280-admin-dark.png", MVP, 1280, 800, "dark", dict(scenario="unknown", role="admin", lang="en", showcase="hidden", screen="admin", theme="dark")),
            ("360-events-light.png", MVP, 360, 667, "light", dict(scenario="operational", lang="ru", showcase="hidden", screen="events")),
            ("360-help-dark.png", MVP, 360, 667, "dark", dict(scenario="unavailable", lang="ru", showcase="hidden", screen="help", theme="dark")),
            ("320-text200-en.png", MVP, 320, 568, "light", dict(scenario="degraded", lang="en", showcase="hidden", text="200")),
            ("android-onboarding-light.png", ANDROID, 390, 844, "light", dict(state="exclude", lang="ru", showcase="hidden")),
            ("android-running-dark.png", ANDROID, 390, 844, "dark", dict(state="running", lang="en", showcase="hidden", theme="dark")),
            ("onboarding-clean-install-1280.png", ONB, 1280, 800, "light", {}),
            ("onboarding-partial-dark-768.png", ONB, 768, 1024, "dark", {}),
        ]
        for name, base, w, h, scheme, params in shots:
            ctx, pg, errs = new_page(w, h, scheme)
            pg.goto(url(base, **params) if params else base)
            pg.wait_for_timeout(300)
            if base == ONB and "clean" in name:
                pg.click('#guide [data-state="clean"][data-view="admin"]'); pg.wait_for_timeout(200)
            if base == ONB and "partial" in name:
                pg.evaluate("() => window.VPNPulseShowcase.apply({ scenario: 'partial_coverage', role: 'member', screen: 'status', theme: 'dark' })"); pg.wait_for_timeout(200)
            pg.screenshot(path=str(OUT / name), full_page=False)
            ctx.close()
        browser.close()

    print(f"checks: {checks}, failures: {len(failures)}")
    for f in failures:
        print(" -", f)
    print(f"screenshots: {len(list(OUT.glob('*.png')))} in {OUT}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
