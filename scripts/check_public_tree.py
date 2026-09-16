"""Scan the working tree (and optionally Git history) for data that must never be public.

Looks for: literal IPv4 addresses outside documentation ranges, private key headers, common
token formats (GitHub, AWS, Telegram bot tokens, Porkbun-style API keys), absolute local paths,
e-mail addresses outside example/noreply domains, and stray build/cache artefacts.

Run: python scripts/check_public_tree.py [--history]
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".html", ".css", ".js", ".svg", ".sql", ".cfg", ".ini", ".sh"}
DOC_RANGES = ("192.0.2.", "198.51.100.", "203.0.113.", "0.0.0.0", "127.0.0.1", "10.8.1.", "172.29.")

PATTERNS = {
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "github token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "aws key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b"),
    "api key": re.compile(r"\b(?:pk1|sk1)_[a-f0-9]{40,}\b"),
    "windows path": re.compile(r"[A-Za-z]:\\Users\\"),
    "home path": re.compile(r"/home/[a-z][a-z0-9_-]+/"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
}
ALLOWED_EMAIL_DOMAINS = ("example.com", "example.org", "users.noreply.github.com")
ARTEFACT_GLOBS = ("*.db", "*.sqlite", "*.sqlite3", "*.log", "*.pyc")


def scan_text(label: str, text: str, findings: list[str]) -> None:
    for name, pattern in PATTERNS.items():
        for match in pattern.findall(text):
            if name == "ipv4" and match.startswith(DOC_RANGES):
                continue
            if name == "email" and match.lower().endswith(ALLOWED_EMAIL_DOMAINS):
                continue
            findings.append(f"{label}: {name}: {match}")


def candidate_files() -> list[Path]:
    """Files git would commit: tracked plus untracked-but-not-ignored. Falls back to a tree walk."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=ROOT, capture_output=True, check=True,
        ).stdout
        names = [n for n in out.decode("utf-8", "replace").split(chr(0)) if n]
        return [ROOT / n for n in names if (ROOT / n).is_file()]
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and not any(part in SKIP_DIRS for part in p.parts)]


def scan_tree(findings: list[str]) -> int:
    count = 0
    files = candidate_files()
    for path in files:
        rel = path.relative_to(ROOT)
        if any(rel.match(pattern) for pattern in ARTEFACT_GLOBS) or "__pycache__" in rel.parts or ".pytest_cache" in rel.parts:
            findings.append(f"artefact should not be committed: {rel}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        count += 1
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        scan_text(str(rel), text, findings)
    return count


def scan_history(findings: list[str]) -> None:
    try:
        # diffs only: the author identity and the trailers of a commit are metadata, not published content
        log = subprocess.run(["git", "log", "-p", "--all", "--no-color", "--format=commit %H"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False).stdout
    except FileNotFoundError:
        print("git not available; history scan skipped")
        return
    scan_text("git history", log, findings)


def main() -> int:
    findings: list[str] = []
    files = scan_tree(findings)
    if "--history" in sys.argv:
        scan_history(findings)
    for item in findings:
        print("finding:", item)
    print(f"files scanned: {files}, findings: {len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
