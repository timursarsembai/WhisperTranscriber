# -*- coding: utf-8 -*-
"""
Localization (i18n) for the app UI.
Use t("key") for translation, set_locale("en") / set_locale("ru") to switch.
Translations are loaded from JSON files in the locales/ folder.
"""
import os
import json

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_translations = {}  # { "en": {"key": "string", ...}, "ru": {...} }
_current = "en"


def _load_locale(code: str) -> dict:
    path = os.path.join(_LOCALES_DIR, f"{code}.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _ensure_loaded(code: str) -> None:
    if code not in _translations:
        _translations[code] = _load_locale(code)


def get_available_locales() -> list:
    """Return list of locale codes that have a JSON file (e.g. ['en', 'ru'])."""
    if not os.path.isdir(_LOCALES_DIR):
        return ["en"]
    return [
        os.path.splitext(f)[0]
        for f in os.listdir(_LOCALES_DIR)
        if f.endswith(".json")
    ] or ["en"]


def set_locale(code: str) -> None:
    """Set current UI language. Loads the locale if not yet loaded."""
    global _current
    code = (code or "en").strip().lower()
    _ensure_loaded(code)
    _current = code if _translations.get(code) else _current


def get_locale() -> str:
    """Return current locale code."""
    return _current


def t(key: str, **kwargs) -> str:
    """
    Translate key for current locale. Returns the key if missing.
    Supports formatting: t("key", name="X") replaces {name} in the string.
    """
    _ensure_loaded(_current)
    s = _translations.get(_current, {}).get(key, _translations.get("en", {}).get(key, key))
    if kwargs:
        try:
            s = s.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return s
