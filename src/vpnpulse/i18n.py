"""Server-side strings: the same RU/EN dictionaries the Mini App uses (i18n/*.json).

The API renders a few texts itself — doctor hints and installation-wide attention messages —
in the language of the request. Keys missing from a dictionary fall back to Russian, then to
the key itself, so a forgotten translation is visible instead of a crash.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


def default_i18n_dir() -> Path:
    env = os.environ.get("VPNPULSE_I18N_DIR")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "i18n"
        if (candidate / "ru.json").exists():
            return candidate
    raise FileNotFoundError("i18n/ru.json not found; set VPNPULSE_I18N_DIR")


@lru_cache(maxsize=4)
def _load(directory: str) -> dict[str, dict[str, str]]:
    out = {}
    for lang in ("ru", "en"):
        path = Path(directory) / f"{lang}.json"
        out[lang] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    return out


class Translator:
    def __init__(self, directory: Path | None = None) -> None:
        self.directory = str(directory or default_i18n_dir())

    def t(self, lang: str, key: str, **params) -> str:
        dictionaries = _load(self.directory)
        text = dictionaries.get(lang, {}).get(key)
        if text is None:
            text = dictionaries.get("ru", {}).get(key, key)
        for name, value in params.items():
            text = text.replace("{" + name + "}", str(value))
        return text

    def duration(self, lang: str, minutes: int | None) -> str:
        if minutes is None:
            return "—"
        if minutes < 1:
            return self.t(lang, "duration.now")
        if minutes < 60:
            return self.t(lang, "duration.min", n=minutes)
        if minutes < 48 * 60:
            return self.t(lang, "duration.hour", n=round(minutes / 60))
        return self.t(lang, "duration.day", n=round(minutes / 1440))
