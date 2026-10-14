"""Measure the probe's screens on a device instead of judging them by eye.

Э1б came out of four numbers nobody had looked at: a heading 16 % taller than the font's own line,
74 px between lines where the token says 63, 1379 px of nothing on the enrolment screen and a step
bar that travelled with the content. This script takes those numbers automatically.

It walks the four onboarding screens (and all four answers of the route check) on an attached
device, dumps the view tree at each stop with `uiautomator`, and checks five things:

  line box   the pitch between lines is exactly the token, and no block carries hidden padding
  measure    no line averages more than 60 characters
  gaps       inside a block, nothing is more than --space-6 apart
  balance    the free space above the block and below it differ by no more than 8 dp
  steps      at 100 % text the four step names each fit on one line

Run (the app must be installed — `android/build.sh install`):

    python scripts/android_layout_report.py                  # light, ru, 100 %
    python scripts/android_layout_report.py --all            # both themes, both languages, 100/200 %
    python scripts/android_layout_report.py --serial R5CW…   # a particular device

Exit code 1 means a threshold was crossed; the table says which screen and which block.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "android" / "app" / "src" / "main" / "res"
PACKAGE = "dev.vpnpulse.probe"
APP_TITLE = "VPN Pulse Probe"
ACTIVITY = f"{PACKAGE}/.MainActivity"
DUMP = "/sdcard/vpnpulse-layout.xml"

# --text-* of web/src/ui-tokens.css, in sp, and the three line-height ratios
SIZES_SP = (12, 14, 16, 20, 24)
RATIOS = (1.2, 1.4, 1.5)
SPACE_6_DP = 32
BALANCE_DP = 8
MAX_CHARS_PER_LINE = 60
# Android does not add the trailing leading: a block of n lines is (n-1) × pitch + the font's own
# box. The box is not a token — it is whatever the system face is, 1.17 em for Roboto — so it is
# measured on this device from the app bar's title, which is always one line of --text-md, and
# every other block then has to fit that arithmetic to the pixel.
FONT_BOX_FALLBACK = 1.17
FIT_TOLERANCE_PX = 1
TITLE_SIZE_SP = 16
# RingView caps its caption at 18 characters and shrinks the text until it fits; a word that long
# never triggers the shrink, so the ring keeps the size the type scale gives it.
RING_MAX_CHARS = 18
RING_WORDS = ("android_cellular_checking", "android_route_ok", "android_route_bad",
              "android_cellular_nosim")
ROUTE_CHECK_WAIT_S = 2.0
# RingView: min(--ring-size × 4, 64 % of the short side) — 672 px here, far above the 44 dp badge
RING_MIN_PX = 300


# ---------------------------------------------------------------- the device

class Device:
    def __init__(self, serial: str | None):
        self.serial = serial

    def adb(self, *args: str, timeout: float = 60) -> str:
        command = ["adb"]
        if self.serial:
            command += ["-s", self.serial]
        command += list(args)
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace")
        if done.returncode != 0:
            raise SystemExit(f"adb {' '.join(args)}: {done.stderr.strip() or done.returncode}")
        return done.stdout

    def shell(self, line: str, timeout: float = 60) -> str:
        return self.adb("shell", line, timeout=timeout)

    def density(self) -> float:
        found = re.search(r"(\d+)", self.shell("wm density").splitlines()[-1])
        if not found:
            raise SystemExit("cannot read the screen density")
        return int(found.group(1)) / 160.0

    def font_scale(self) -> float:
        raw = self.shell("settings get system font_scale").strip()
        try:
            return float(raw)
        except ValueError:
            return 1.0

    def set_font_scale(self, scale: float) -> None:
        self.shell(f"settings put system font_scale {scale}")

    def set_night(self, on: bool) -> None:
        self.shell(f"cmd uimode night {'yes' if on else 'no'}")

    def restart_app(self) -> None:
        self.shell(f"am force-stop {PACKAGE}")
        self.shell(f"am start -n {ACTIVITY}")
        time.sleep(1.2)

    def tree(self) -> ET.Element:
        for attempt in range(4):
            self.shell(f"uiautomator dump {DUMP}")
            xml = self.adb("exec-out", "cat", DUMP)
            if xml.lstrip().startswith("<"):
                return ET.fromstring(xml)
            time.sleep(0.6)
        raise SystemExit("uiautomator gave nothing that looks like a view tree")

    def tap(self, box: tuple[int, int, int, int]) -> None:
        self.shell(f"input tap {(box[0] + box[2]) // 2} {(box[1] + box[3]) // 2}")
        time.sleep(0.6)

    def long_press(self, box: tuple[int, int, int, int]) -> None:
        x, y = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        self.shell(f"input swipe {x} {y} {x} {y} 800")
        time.sleep(0.6)

    def type(self, value: str) -> None:
        self.shell(f"input text {value}")
        time.sleep(0.4)


# ---------------------------------------------------------------- the view tree

BOUNDS = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def box(node: ET.Element) -> tuple[int, int, int, int]:
    found = BOUNDS.match(node.get("bounds", ""))
    if not found:
        return (0, 0, 0, 0)
    left, top, right, bottom = (int(g) for g in found.groups())
    return (left, top, right, bottom)


def height(node: ET.Element) -> int:
    left, top, right, bottom = box(node)
    return bottom - top


def walk(node: ET.Element, parent: ET.Element | None = None):
    yield node, parent
    for child in node:
        yield from walk(child, node)


def clickable_chain(node: ET.Element, parents: dict) -> bool:
    while node is not None:
        if node.get("clickable") == "true":
            return True
        node = parents.get(id(node))
    return False


def strings(lang: str) -> dict[str, str]:
    path = RES / ("values-ru" if lang == "ru" else "values") / "strings.xml"
    found = {}
    for element in ET.parse(path).getroot():
        if element.tag == "string" and element.get("name"):
            found[element.get("name")] = "".join(element.itertext())
    return found


# ---------------------------------------------------------------- the checks

class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []
        self.failures = 0

    def add(self, where: str, check: str, verdict: str, detail: str) -> None:
        self.rows.append((where, check, verdict, detail))
        if verdict == "FAIL":
            self.failures += 1

    def print(self) -> None:
        width = max(len(r[0]) for r in self.rows)
        for where, check, verdict, detail in self.rows:
            mark = "ok  " if verdict == "ok" else "FAIL"
            print(f"{where:<{width}}  {mark}  {check:<10} {detail}")


def line_boxes(density: float, scale: float) -> list[tuple[int, int, int, float]]:
    """(pitch in px, text size in px, size in sp, ratio) for every token pair the app can use."""
    out = []
    for size in SIZES_SP:
        px = round(size * density * scale)
        for ratio in RATIOS:
            out.append((round(px * ratio), px, size, ratio))
    return out


def font_box(tree: ET.Element, density: float, scale: float) -> float:
    """The face's own line box, in em, measured from the app bar's title: one line of --text-md."""
    for node, parent in walk(tree):
        if (node.get("text") or "").strip() == APP_TITLE:
            return height(node) / (TITLE_SIZE_SP * density * scale)
    return FONT_BOX_FALLBACK


def fit(tall: int, boxes: list[tuple[int, int, int, float]], em: float):
    """(error in px, size, ratio, lines) for the token pair that explains a block this tall."""
    best = None
    for pitch, px, size, ratio in boxes:
        if pitch <= 0 or px <= 0:
            continue
        box_px = round(em * px)
        for lines in range(1, 9):
            error = abs(tall - ((lines - 1) * pitch + box_px))
            if best is None or error < best[0]:
                best = (error, size, ratio, lines)
            if (lines - 1) * pitch + box_px > tall:
                break
    return best


def check_text_metrics(report: Report, where: str, tree: ET.Element,
                       boxes: list[tuple[int, int, int, float]], em: float) -> None:
    parents = {}
    for node, parent in walk(tree):
        parents[id(node)] = parent
    worst = None
    long_lines = []
    for node, parent in walk(tree):
        text = (node.get("text") or "").strip()
        if not text or len(node) or clickable_chain(node, parents):
            continue          # containers, buttons and the code field have their own metrics
        tall = height(node)
        best = fit(tall, boxes, em)
        if best is None:
            continue
        error, size, ratio, lines = best
        if worst is None or error > worst[0]:
            worst = (error, text, size, ratio, lines, tall)
        if len(text) / lines > MAX_CHARS_PER_LINE:
            long_lines.append((round(len(text) / lines), text))
    if worst:
        error, text, size, ratio, lines, tall = worst
        verdict = "ok" if error <= FIT_TOLERANCE_PX else "FAIL"
        report.add(where, "line box", verdict,
                   f"worst block {error} px off the token: {tall} px = {lines} line(s)"
                   f" of {size} sp × {ratio} with a {em:.3f} em face — {text[:28]!r}")
    if long_lines:
        chars, text = max(long_lines)
        report.add(where, "measure", "FAIL", f"{chars} characters a line: {text[:48]!r}")
    else:
        report.add(where, "measure", "ok", f"≤ {MAX_CHARS_PER_LINE} characters a line")


def content_column(tree: ET.Element) -> tuple[ET.Element, ET.Element] | None:
    for node, parent in walk(tree):
        if node.get("class") == "android.widget.ScrollView" and len(node):
            return node, node[0]
    return None


def check_rhythm(report: Report, where: str, tree: ET.Element, density: float) -> None:
    found = content_column(tree)
    if not found:
        report.add(where, "rhythm", "FAIL", "no scrolling content on this screen")
        return
    scroll, column = found
    children = [child for child in column if height(child) > 0]
    if not children:
        return
    limit = round(SPACE_6_DP * density)
    gaps = []
    for node, parent in walk(column):          # every pair of neighbours, however deep
        siblings = [child for child in node if height(child) > 0]
        for before, after in zip(siblings, siblings[1:]):
            gaps.append((box(after)[1] - box(before)[3], after))
    if gaps:
        widest, node = max(gaps, key=lambda pair: pair[0])
        verdict = "ok" if widest <= limit else "FAIL"
        said = (node.get("text") or node.get("content-desc") or "").strip()
        report.add(where, "gaps", verdict,
                   f"widest gap inside the block {widest} px (limit {limit})"
                   + (f", before {said[:30]!r}" if verdict == "FAIL" else ""))
    above = box(children[0])[1] - box(scroll)[1]
    below = box(scroll)[3] - box(children[-1])[3]
    allowed = round(BALANCE_DP * density)
    verdict = "ok" if abs(above - below) <= allowed else "FAIL"
    report.add(where, "balance", verdict,
               f"{above} px above the block, {below} px below (allowed {allowed} px apart)")


def check_step_bar(report: Report, where: str, tree: ET.Element) -> None:
    labels = []
    for node, parent in walk(tree):
        # uiautomator reports the base class, so the bar is known by what a screen reader hears
        if " → " in (node.get("content-desc") or ""):
            labels = [child for child, _ in walk(node) if (child.get("text") or "").strip()]
            break
    if not labels:
        # the bar's names are not individually accessible: measure the bar itself instead
        return
    heights = [height(node) for node in labels]
    verdict = "ok" if max(heights) <= min(heights) * 1.5 else "FAIL"
    report.add(where, "steps", verdict,
               f"step names {min(heights)}–{max(heights)} px tall ({len(labels)} names)")


def check_ring_words(report: Report, lang: str) -> None:
    words = strings(lang)
    too_long = [(name, words.get(name, "")) for name in RING_WORDS
                if len(words.get(name, "")) > RING_MAX_CHARS]
    if too_long:
        name, value = max(too_long, key=lambda pair: len(pair[1]))
        report.add(f"{lang}: ring", "ring", "FAIL",
                   f"{name} is {len(value)} characters, the ring shrinks its text: {value!r}")
    else:
        longest = max(RING_WORDS, key=lambda name: len(words.get(name, "")))
        report.add(f"{lang}: ring", "ring", "ok",
                   f"longest word {len(words.get(longest, ''))} ≤ {RING_MAX_CHARS} characters")


# ---------------------------------------------------------------- the walk

def tappable(tree: ET.Element, value: str) -> tuple[int, int, int, int] | None:
    """The first node with this text that sits inside something pressable.

    "Done" is both the fourth step's name and the button that gets there, so the search cannot
    stop at the first match: the step bar's names are deliberately not clickable.
    """
    parents = {id(node): parent for node, parent in walk(tree)}
    for node, parent in walk(tree):
        if (node.get("text") or "").strip() != value:
            continue
        up = node
        while up is not None:
            if up.get("clickable") == "true":
                return box(up)
            up = parents.get(id(up))
    return None


def text_of(tree: ET.Element, cls: str) -> str:
    for node, parent in walk(tree):
        if node.get("class") == cls:
            return (node.get("text") or "").strip()
    return ""


def ring_box(tree: ET.Element) -> tuple[int, int, int, int] | None:
    """uiautomator names a custom view by its base class, so the ring is found by its shape:
    a childless square that says something to a screen reader and is big enough to be the ring."""
    best = None
    for node, parent in walk(tree):
        left, top, right, bottom = box(node)
        wide, tall = right - left, bottom - top
        if len(node) or not (node.get("content-desc") or "").strip():
            continue
        # the biggest square on the screen: the language badge is square too, and much smaller
        if wide > RING_MIN_PX and abs(wide - tall) <= 8 and (best is None or wide > best[0]):
            best = (wide, box(node))
    return best[1] if best else None


def screens(device: Device, words: dict[str, str], cycle: bool):
    """Walk the onboarding and yield (name, view tree) at every stop.

    The app is already started and in the language we want: restarting here would throw the
    language away, because the choice lives in the activity and not in the system settings.
    """
    tree = device.tree()
    yield "bind", tree

    field = None
    for node, parent in walk(tree):
        if node.get("class") == "android.widget.EditText":
            field = box(node)
    if not field:
        raise SystemExit("no code field on the first screen")
    for attempt in range(3):
        device.tap(field)
        device.type("ABCD1234")
        if text_of(device.tree(), "android.widget.EditText") == "ABCD1234":
            break
    else:
        raise SystemExit("the code would not go into the field")
    spot = tappable(device.tree(), words["android_bind_action"])
    if not spot:
        raise SystemExit("the enrolment button is not on the screen")
    device.tap(spot)

    tree = device.tree()
    yield "exclude", tree
    spot = tappable(tree, words["android_exclude_confirm"])
    if not spot:
        raise SystemExit("the exclusion button is not on the screen")
    device.tap(spot)

    time.sleep(ROUTE_CHECK_WAIT_S)
    tree = device.tree()
    yield "route: confirmed", tree

    if cycle:
        for name in ("route: not confirmed", "route: no network", "route: checking"):
            spot = ring_box(tree)
            if not spot:
                break
            device.long_press(spot)
            tree = device.tree()
            yield name, tree
        spot = ring_box(tree)
        if spot:
            device.long_press(spot)       # back to confirmed, where the button lives
            tree = device.tree()

    spot = tappable(tree, words["android_step_done"])
    if not spot:
        raise SystemExit("the button that ends the route check is not on the screen")
    device.tap(spot)
    yield "done", device.tree()


def language(device: Device, want: str, words_other: str) -> None:
    """The badge in the app bar shows the other language: tap it when it is not the one we want."""
    tree = device.tree()
    spot = tappable(tree, words_other)
    if spot:
        device.tap(spot)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial")
    parser.add_argument("--all", action="store_true", help="both themes, both languages, 100/200 %%")
    parser.add_argument("--lang", default="ru")
    parser.add_argument("--theme", default="light", choices=("light", "dark"))
    parser.add_argument("--font", type=float, default=1.0)
    parser.add_argument("--no-cycle", action="store_true", help="skip the other three route answers")
    options = parser.parse_args()

    device = Device(options.serial)
    density = device.density()
    was_scale = device.font_scale()
    report = Report()

    runs = []
    if options.all:
        for theme in ("light", "dark"):
            for lang in ("ru", "en"):
                for font in (1.0, 2.0):
                    runs.append((theme, lang, font))
    else:
        runs.append((options.theme, options.lang, options.font))

    try:
        for theme, lang, font in runs:
            device.set_night(theme == "dark")
            device.set_font_scale(font)
            device.restart_app()
            words = strings(lang)
            other = strings("en" if lang == "ru" else "ru")
            language(device, lang, other["app_lang_other"])
            boxes = line_boxes(density, font)
            check_ring_words(report, lang)
            em = font_box(device.tree(), density, font)
            for name, tree in screens(device, words, not options.no_cycle):
                where = f"{theme}/{lang}/{int(font * 100)} % {name}"
                check_text_metrics(report, where, tree, boxes, em)
                check_rhythm(report, where, tree, density)
                if font == 1.0:
                    check_step_bar(report, where, tree)
    finally:
        device.set_font_scale(was_scale)

    report.print()
    print(f"\n{len(report.rows)} checks, {report.failures} failed"
          f" — density {density}, {len(runs)} run(s)")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
