"""Measure the probe's screens on a device instead of judging them by eye.

Э1б came out of four numbers nobody had looked at: a heading 16 % taller than the font's own line,
74 px between lines where the token says 63, 1379 px of nothing on the enrolment screen and a step
bar that travelled with the content. This script takes those numbers automatically.

It walks the four onboarding screens (and all four answers of the route check) on an attached
device, dumps the view tree at each stop with `uiautomator`, and checks six things:

  line box   every block is (n-1) x pitch + the face's own box, to the pixel, for the one token
             pair its role in the code gives it — at 100 % text only, see NON_LINEAR_NOTE
  measure    no line averages more than MAX_CHARS_PER_LINE characters
  gaps       nothing stacked overlaps, and nothing is more than --space-6 apart
  balance    the free space above the block and below it differ by no more than 8 dp
  step bar   it is in the shell, not in the scrolling content, and names four steps at 100 %
             text or one past LARGE_TEXT, each on a single line
  ring       RingView never had to wrap or shrink its word, by its own report in the log

The device is handed back as it was found — theme, font scale and the keep-the-screen-on setting
are read first and restored at the end — and a locked one is refused rather than measured.

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
ACTIVITY = f"{PACKAGE}/.MainActivity"
DUMP = "/sdcard/vpnpulse-layout.xml"

# Every block the app draws, against the one token pair its role in the code gives it. Searching
# the whole type scale instead would prove nothing: a 24 sp heading of 85 px — exactly the defect
# Э1б was written to remove — is also, to the pixel, two lines of 12 sp × 1.5.
#
# CONTENT: what Onboarding.java puts in the scrolling column, by the Views.* helper it is built
# with — heading = --text-xl/--lh-tight, body and muted = --text-md/--lh-normal, note and label =
# --text-sm/--lh-caption. CHROME: the app bar and the step bar, which MainActivity and StepBar
# build. "Готово" is in both, as the fourth step's name and as the last screen's heading, so the
# two tables are looked up by where the node sits, not by the word alone.
CONTENT_ROLES = {
    "android_bind_title": (24, 1.2),
    "android_exclude": (24, 1.2),
    "android_step_done": (24, 1.2),
    "android_bind_body": (16, 1.5),
    "android_done_body": (16, 1.5),
    "android_exclude_step1": (16, 1.5),
    "android_exclude_step2": (16, 1.5),
    "android_exclude_step3": (16, 1.5),
    "android_bind_code": (14, 1.4),
    "android_bind_error": (14, 1.4),
    "android_exclude_why": (14, 1.4),
    "android_cellularready": (14, 1.4),
    "android_cellular_ok": (14, 1.4),
    "android_cellular_fail": (14, 1.4),
    "android_cellular_fix": (14, 1.4),
}
CHROME_ROLES = {
    "android_title": (16, 1.2),
    "android_subtitle": (12, 1.4),
    "android_step_bind": (12, 1.4),
    "android_step_exclude": (12, 1.4),
    "android_step_cellular": (12, 1.4),
    "android_step_done": (12, 1.4),
}
STEP_NAME_SP, STEP_NAME_RATIO = 12, 1.4
SPACE_6_DP = 32
BALANCE_DP = 8
# A ceiling for copy yet to be written, not a current complaint: today's longest string is 57
# characters. It bites exactly on blocks that fit one line, where the text IS the line.
MAX_CHARS_PER_LINE = 50
# Android does not add the trailing leading: a block of n lines is (n-1) × pitch + the font's own
# box. The box is not a token — it is whatever the system face is, 1.17 em for Roboto — so it is
# measured on this device from the app bar's title, which is always one line of --text-md, and
# every other block then has to fit that arithmetic to the pixel. A run that cannot find the
# title stops rather than guess.
FIT_TOLERANCE_PX = 1
TITLE_SIZE_SP = 16
# Android 14 scales sp through a curve, not a factor: at a system scale of 2.0 a 16 sp line grows
# 1.76x, and a large size grows less than a small one, on purpose. Measured here: the face is
# 1.167 em of 16 sp at 100 % and 1.024 em of a doubled 16 sp at 200 %. So above 100 % the token
# arithmetic no longer predicts the pixel height, and the pitch check is not run above 100 %.
# What the 200 % pass does still check: that no two blocks overlap and none drift more than
# --space-6 apart, that the block stays centred, that the step bar collapses to one name, and
# that the ring does not have to wrap or shrink more than a large font excuses.
NON_LINEAR_NOTE = "skipped above 100 %: Android scales sp through a curve, so the tokens do not predict px"
# StepBar.LARGE_TEXT — past this the bar names only the step in hand.
LARGE_TEXT = 1.3
# RingView logs this tag when it has to shrink its own text; canvas text is invisible to
# uiautomator, so the log is the only way to see Э1б's second defect come back.
RING_TAG = "vpnpulse-ring"

# A character the UI face does not have — an arrow, an emoji — is drawn by another font, and the
# line grows to that font's box. The pitch is still the token, so such a block is allowed to be
# up to a quarter of an em taller than the face would make it.
FALLBACK_SLACK_EM = 0.25
CYRILLIC_END = 0x04FF
DASHES = (0x2010, 0x2027)
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

    def night(self) -> str:
        """The device's own setting, so a run can hand it back: "yes", "no" or "auto"."""
        said = self.shell("cmd uimode night").strip().lower()
        for value in ("yes", "no", "auto", "custom_schedule", "custom_bedtime"):
            if said.endswith(value):
                return value
        return "auto"

    def awake(self) -> None:
        """A phone left alone turns its screen off, and uiautomator then dumps the lock screen."""
        self.shell("input keyevent KEYCODE_WAKEUP")

    def locked(self) -> bool:
        said = self.shell("dumpsys window")
        return "mDreamingLockscreen=true" in said

    def stay_on(self) -> str:
        return self.shell("settings get global stay_on_while_plugged_in").strip() or "0"

    def set_stay_on(self, value: str) -> None:
        self.shell(f"settings put global stay_on_while_plugged_in {value}")

    def set_night(self, on) -> None:
        self.shell(f"cmd uimode night {on if isinstance(on, str) else ('yes' if on else 'no')}")

    def restart_app(self) -> None:
        self.awake()
        self.shell(f"am force-stop {PACKAGE}")
        self.ring_mark = len(self.ring_log())
        self.shell(f"am start -n {ACTIVITY}")
        time.sleep(1.2)

    def ring_log(self) -> list[str]:
        """Every line RingView has written about shrinking its text, oldest first."""
        said = self.adb("logcat", "-d", "-s", f"{RING_TAG}:D")
        return [line for line in said.splitlines() if "ring text" in line]

    def ring_shrinks(self) -> list[str]:
        """The ones since the app was last started."""
        return self.ring_log()[getattr(self, "ring_mark", 0):]

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

    def key(self, name: str) -> None:
        self.shell(f"input keyevent KEYCODE_{name}")
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


def role_map(lang: str) -> dict:
    """{("content"|"chrome", the words on screen): (size in sp, ratio)} for this language."""
    words = strings(lang)
    out = {}
    for place, table in (("content", CONTENT_ROLES), ("chrome", CHROME_ROLES)):
        for name, role in table.items():
            if name in words:
                out[(place, words[name])] = role
    return out


def needs_fallback(text: str) -> bool:
    """True when the text holds a character the UI face is unlikely to carry — an arrow, an emoji.

    Such a character is drawn by another font and the line grows to that font's box, so the block
    is taller than the type scale alone would make it. The pitch between lines is still the token.
    """
    return any(ord(c) > CYRILLIC_END and not (DASHES[0] <= ord(c) <= DASHES[1]) for c in text)


def font_box(tree: ET.Element, density: float, scale: float) -> float:
    """The face's own line box, in em, measured from the app bar's title: one line of --text-md."""
    title = strings("en")["android_title"]      # the product's name, the same in both languages
    for node, parent in walk(tree):
        if (node.get("text") or "").strip() == title:
            return height(node) / sp_px(TITLE_SIZE_SP, density, scale)
    raise SystemExit(f"the app bar does not say {title!r}: the face cannot be measured")


def sp_px(size: int, density: float, scale: float) -> int:
    """sp to pixels the way Android rounds it — (int)(x + 0.5), not Python's round to even."""
    return int(size * density * scale + 0.5)


def fit_role(tall: int, size: int, ratio: float, density: float, scale: float,
             em: float, slack: float):
    """(error in px, lines) for a block of this role: n lines, no other size and no other ratio."""
    px = sp_px(size, density, scale)
    pitch = int(px * ratio + 0.5)
    box_px = int(em * px + 0.5)
    room = int(slack * px + 0.5)
    best = None
    for lines in range(1, 12):
        floor = (lines - 1) * pitch + box_px
        error = max(floor - tall, tall - floor - room, 0)
        if best is None or error < best[0]:
            best = (error, lines)
        if floor > tall:
            break
    return best


def blocks(tree: ET.Element, roles: dict) -> list[tuple[ET.Element, str, tuple]]:
    """Every leaf of text the type scale is responsible for, with the role its place gives it."""
    parents = {id(node): parent for node, parent in walk(tree)}
    scroll = content_column(tree)
    inside = set()
    if scroll:
        for node, parent in walk(scroll[0]):
            inside.add(id(node))
    out = []
    for node, parent in walk(tree):
        text = (node.get("text") or "").strip()
        if not text or len(node) or clickable_chain(node, parents):
            continue          # containers, buttons and the code field have their own metrics
        left, top, right, bottom = box(node)
        if len(text) <= 2 and abs((right - left) - (bottom - top)) <= 2:
            continue          # a disc or a badge: sized by --space-5 or --control-min, not by type
        where = "content" if id(node) in inside else "chrome"
        role = roles.get((where, text))
        out.append((node, text, role))
    return out


def check_text_metrics(report: Report, where: str, tree: ET.Element, roles: dict,
                       density: float, em: float, scale: float) -> None:
    found = blocks(tree, roles)
    unknown = [text for _, text, role in found if role is None]
    known = [(node, text, role) for node, text, role in found if role is not None]
    if not known:
        report.add(where, "line box", "FAIL", "no block on this screen had a known role to check")
        return

    worst = None
    long_lines = []
    for node, text, (size, ratio) in known:
        slack = FALLBACK_SLACK_EM if needs_fallback(text) else 0.0
        error, lines = fit_role(height(node), size, ratio, density, scale, em, slack)
        if worst is None or error > worst[0]:
            worst = (error, text, size, ratio, lines, height(node))
        if len(text) / lines > MAX_CHARS_PER_LINE:
            long_lines.append((round(len(text) / lines), text))

    skipped = f", {len(unknown)} with no role" if unknown else ""
    if scale > 1.0:
        report.add(where, "line box", "ok", f"{NON_LINEAR_NOTE} ({len(known)} blocks{skipped})")
    else:
        error, text, size, ratio, lines, tall = worst
        verdict = "ok" if error <= FIT_TOLERANCE_PX else "FAIL"
        report.add(where, "line box", verdict,
                   f"{len(known)} blocks{skipped}, worst {error} px off: {tall} px vs"
                   f" {lines} line(s) of {size} sp × {ratio} on a {em:.3f} em face — {text[:26]!r}")
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
            # only what is stacked: a numbered disc and its line sit side by side, and the
            # vertical distance between them is meaningless
            if box(after)[0] >= box(before)[2] - 1:
                continue
            gaps.append((box(after)[1] - box(before)[3], after))
    if gaps:
        widest, node = max(gaps, key=lambda pair: pair[0])
        tightest, over = min(gaps, key=lambda pair: pair[0])
        said = (node.get("text") or node.get("content-desc") or "").strip()
        if tightest < 0:
            crossed = (over.get("text") or over.get("content-desc") or "").strip()
            report.add(where, "gaps", "FAIL",
                       f"two blocks overlap by {-tightest} px, at {crossed[:30]!r}")
        else:
            verdict = "ok" if widest <= limit else "FAIL"
            report.add(where, "gaps", verdict,
                       f"gaps {tightest}–{widest} px inside the block (limit {limit})"
                       + (f", widest before {said[:30]!r}" if verdict == "FAIL" else ""))
    # the step bar belongs to the shell: inside the scrolling column it would travel with the
    # content again, and "balance" alone cannot see that, because the column is centred as a whole
    in_column = any(" → " in (node.get("content-desc") or "") for node, _ in walk(column))
    report.add(where, "step bar", "FAIL" if in_column else "ok",
               "inside the scrolling content" if in_column else "in the shell, above the content")
    above = box(children[0])[1] - box(scroll)[1]
    below = box(scroll)[3] - box(children[-1])[3]
    allowed = round(BALANCE_DP * density)
    verdict = "ok" if abs(above - below) <= allowed else "FAIL"
    report.add(where, "balance", verdict,
               f"{above} px above the block, {below} px below (allowed {allowed} px apart)")


def check_step_bar(report: Report, where: str, tree: ET.Element,
                   density: float, em: float, scale: float) -> None:
    labels = []
    for node, parent in walk(tree):
        # uiautomator reports the base class, so the bar is known by what a screen reader hears
        if " → " in (node.get("content-desc") or ""):
            labels = [child for child, _ in walk(node) if (child.get("text") or "").strip()]
            break
    if not labels:
        report.add(where, "steps", "FAIL", "no step bar on this screen, or it says nothing aloud")
        return
    heights = [height(node) for node in labels]
    # against a known one line of --text-xs, not against each other: four names that ALL wrap
    # have the same height as each other and would otherwise pass
    one = int(em * sp_px(STEP_NAME_SP, density, scale) + 0.5)
    one_line = max(heights) <= one * 1.5
    wanted = ("4 names, one line each" if scale < LARGE_TEXT
              else "1 name, one line")   # past a large font four names break words in half
    count = 4 if scale < LARGE_TEXT else 1
    verdict = "ok" if len(labels) == count and one_line else "FAIL"
    report.add(where, "steps", verdict,
               f"{len(labels)} name(s), {min(heights)}–{max(heights)} px tall against"
               f" {one} px for one line (want {wanted})")


def check_ring_shrink(report: Report, where: str, device, scale: float) -> None:
    """Did the ring have to wrap or shrink its word? Canvas text is invisible to uiautomator, so
    RingView says so in the log and this is the only check that sees Э1б's second defect."""
    shrunk = device.ring_shrinks()
    if scale >= LARGE_TEXT:
        report.add(where, "ring", "ok",
                   f"{len(shrunk)} wrap(s) or shrink(s), allowed at this font size")
        return
    if shrunk:
        report.add(where, "ring", "FAIL", shrunk[-1].strip()[-90:])
    else:
        report.add(where, "ring", "ok", "the ring drew its word at the size the scale gives it")


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


def text_of(tree: ET.Element, cls: str):
    """What that kind of view says, or None when the screen has no such view at all."""
    for node, parent in walk(tree):
        if node.get("class") == cls:
            return (node.get("text") or "").strip()
    return None


def pressable(tree: ET.Element) -> list[str]:
    """What this screen offers to press — so a failure says what was there instead."""
    parents = {id(node): parent for node, parent in walk(tree)}
    out = []
    for node, parent in walk(tree):
        text = (node.get("text") or "").strip()
        if text and not len(node) and clickable_chain(node, parents):
            out.append(text)
    return out


def ring_says(tree: ET.Element) -> str:
    """What the ring is announcing — the state word, which is how a state change is seen."""
    for node, parent in walk(tree):
        left, top, right, bottom = box(node)
        if len(node) or not (node.get("content-desc") or "").strip():
            continue
        if right - left > RING_MIN_PX and abs((right - left) - (bottom - top)) <= 8:
            return (node.get("content-desc") or "").strip()
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
        # a real phone answers the tap with a soft keyboard, and uiautomator then dumps the
        # keyboard's window instead of the app's: put it away before looking
        device.key("ESCAPE")
        typed = text_of(device.tree(), "android.widget.EditText")
        if typed == "ABCD1234":
            break
        if typed is None:
            device.key("BACK")      # ESCAPE does not close every vendor's keyboard
            if text_of(device.tree(), "android.widget.EditText") == "ABCD1234":
                break
    else:
        raise SystemExit("the code would not go into the field")
    spot = tappable(device.tree(), words["android_bind_action"])
    if not spot:
        raise SystemExit(f"the enrolment button is not on the screen;"
                         f" what can be pressed: {pressable(tree)}")
    device.tap(spot)

    tree = device.tree()
    yield "exclude", tree
    spot = tappable(tree, words["android_exclude_confirm"])
    if not spot:
        raise SystemExit(f"the exclusion button is not on the screen;"
                         f" what can be pressed: {pressable(tree)}")
    device.tap(spot)

    time.sleep(ROUTE_CHECK_WAIT_S)
    tree = device.tree()
    yield "route: confirmed", tree

    if cycle:
        for name in ("route: not confirmed", "route: no network", "route: checking"):
            spot = ring_box(tree)
            if not spot:
                raise SystemExit(f"the ring is not on the screen, so {name} cannot be reached")
            was = ring_says(tree)
            device.long_press(spot)
            tree = device.tree()
            if ring_says(tree) == was:
                # a missed long press would otherwise be reported as three screens measured
                raise SystemExit(f"the long press did not change the ring: still {was!r}")
            yield name, tree
        spot = ring_box(tree)
        if spot:
            device.long_press(spot)       # back to confirmed, where the button lives
            tree = device.tree()

    spot = tappable(tree, words["android_step_done"])
    if not spot:
        raise SystemExit(f"the button that ends the route check is not on the screen;"
                         f" what can be pressed: {pressable(tree)}")
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
    device.awake()
    if device.locked():
        print("the device is locked — unlock it and run this again; a lock screen measures nothing",
              file=sys.stderr)
        return 2
    density = device.density()
    # the device is someone's phone: remember what it was set to and hand it back
    was_scale = device.font_scale()
    was_night = device.night()
    was_stay_on = device.stay_on()
    device.set_stay_on("3")      # AC | USB, so the screen does not go dark mid-walk
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
            check_ring_words(report, lang)
            em = font_box(device.tree(), density, font)
            roles = role_map(lang)
            for name, tree in screens(device, words, not options.no_cycle):
                where = f"{theme}/{lang}/{int(font * 100)} % {name}"
                check_text_metrics(report, where, tree, roles, density, em, font)
                check_rhythm(report, where, tree, density)
                check_step_bar(report, where, tree, density, em, font)
                check_ring_shrink(report, where, device, font)
    finally:
        device.set_font_scale(was_scale)
        device.set_night(was_night)
        device.set_stay_on(was_stay_on)

    report.print()
    print(f"\n{len(report.rows)} checks, {report.failures} failed"
          f" — density {density}, {len(runs)} run(s)")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
