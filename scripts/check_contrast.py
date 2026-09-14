"""Check WCAG contrast of the VPN Pulse design tokens (docs/prototypes/ui-tokens.css).

Text pairs must reach 4.5:1, non-text pairs (control boundaries, lamps, focus ring) 3:1.
Both themes are checked: the light palette in `:root {}` and the dark one in
`:root[data-theme="dark"] {}`. Semi-transparent tokens are composited over the background
they are drawn on before measuring. Exit code 1 when any pair fails.

Run: python scripts/check_contrast.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / "docs" / "prototypes" / "ui-tokens.css"

TEXT = 4.5
UI = 3.0


def srgb_to_lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (srgb_to_lin(x) for x in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    la, lb = luminance(a), luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def parse_hex(s: str) -> tuple[float, float, float]:
    s = s.lstrip("#")
    if len(s) == 3:
        s = "".join(ch * 2 for ch in s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def composite(fg: tuple[float, float, float], alpha: float, bg: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(fg[i] * alpha + bg[i] * (1 - alpha) for i in range(3))  # type: ignore[return-value]


def parse_block(css: str, selector: str) -> dict[str, str]:
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", css, re.S)
    if not m:
        raise SystemExit(f"block {selector!r} not found in {TOKENS}")
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if line.startswith("--") and ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().rstrip(";")
    return out


def color(tokens: dict[str, str], name: str, over: tuple[float, float, float]) -> tuple[float, float, float]:
    v = tokens[name]
    if v.startswith("#"):
        return parse_hex(v)
    m = re.match(r"rgba\(\s*(\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\)", v)
    if m:
        return composite((int(m[1]), int(m[2]), int(m[3])), float(m[4]), over)
    raise SystemExit(f"cannot parse {name}: {v}")


def gradient_stops(tokens: dict[str, str], name: str) -> list[tuple[float, float, float]]:
    return [parse_hex(h) for h in re.findall(r"#[0-9a-fA-F]{6}", tokens[name])]


def check_theme(label: str, tokens: dict[str, str]) -> list[str]:
    bg = color(tokens, "--color-bg", (0, 0, 0))
    surface = color(tokens, "--color-surface", bg)
    raised = color(tokens, "--color-raised", bg)
    well = color(tokens, "--color-well", bg)
    text = color(tokens, "--color-text", bg)
    muted = color(tokens, "--color-muted", bg)
    accent = color(tokens, "--color-accent", bg)
    accent_text = color(tokens, "--color-accent-text", bg)
    lamps = {k: color(tokens, f"--color-{k}", bg) for k in ("operational", "degraded", "unavailable", "unknown", "admin")}
    border_strong_bg = color(tokens, "--color-border-strong", bg)
    border_strong_surface = color(tokens, "--color-border-strong", surface)
    metal = gradient_stops(tokens, "--metal")

    pairs: list[tuple[str, tuple, tuple, float]] = [
        ("text on bg", text, bg, TEXT),
        ("text on surface", text, surface, TEXT),
        ("text on raised", text, raised, TEXT),
        ("text on well", text, well, TEXT),
        ("muted on bg (captions, nav labels)", muted, bg, TEXT),
        ("muted on surface (panels, hint)", muted, surface, TEXT),
        ("muted on raised (selected segment caption)", muted, raised, TEXT),
        ("muted on well (unselected segment)", muted, well, TEXT),
        ("accent on bg (text buttons, links)", accent, bg, TEXT),
        ("bg on text (toast)", bg, text, TEXT),
        ("border-strong on bg (ghost button outline)", border_strong_bg, bg, UI),
        ("border-strong on surface (outline in panels)", border_strong_surface, surface, UI),
        ("accent on bg (nav indicator, focus ring)", accent, bg, UI),
    ]
    for k, c in lamps.items():
        pairs.append((f"{k} on bg (state text, arcs)", c, bg, TEXT))
        pairs.append((f"{k} on surface (state text in panels)", c, surface, TEXT))
        if k != "admin":
            pairs.append((f"accent-text glyph on {k} lamp badge", accent_text, c, UI))
            pairs.append((f"bg glyph on {k} ring mark", bg, c, UI))
    for i, stop in enumerate(metal):
        pairs.append((f"accent-text on metal stop {i + 1} (primary button)", accent_text, stop, TEXT))
        pairs.append((f"metal stop {i + 1} against bg (primary button boundary)", stop, bg, UI))

    failures: list[str] = []
    width = max(len(p[0]) for p in pairs)
    print(f"\n[{label}]")
    for name, a, b, need in pairs:
        r = ratio(a, b)
        ok = r >= need
        print(f"  {'ok ' if ok else 'FAIL'} {name.ljust(width)}  {r:5.2f}:1  (need {need})")
        if not ok:
            failures.append(f"{label}: {name} = {r:.2f}:1 < {need}")
    return failures


def main() -> int:
    css = TOKENS.read_text(encoding="utf-8")
    light = parse_block(css, ":root")
    dark = parse_block(css, ':root[data-theme="dark"]')
    # the dark block inside the media query must mirror the explicit one
    media = re.search(r'@media \(prefers-color-scheme: dark\) \{\s*:root:not\(\[data-theme="light"\]\) \{(.*?)\n  \}', css, re.S)
    if media:
        mirrored = {}
        for line in media.group(1).splitlines():
            line = line.strip()
            if line.startswith("--"):
                k, v = line.split(":", 1)
                mirrored[k.strip()] = v.strip().rstrip(";")
        diff = {k for k in set(mirrored) | set(dark) if mirrored.get(k) != dark.get(k)}
        if diff:
            print("dark theme blocks differ:", ", ".join(sorted(diff)))
            return 1
    failures = check_theme("light", light) + check_theme("dark", {**light, **dark})
    print()
    if failures:
        print("contrast FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("contrast OK: all text pairs >= 4.5:1, non-text pairs >= 3:1 in both themes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
