# -*- coding: utf-8 -*-
"""
Localization (i18n) for the app UI.
Use t("key") for translation, set_locale("en") / set_locale("ru") to switch.
Translations are loaded from JSON files in the locales/ folder.
Выбор языка сохраняется в config и восстанавливается при запуске.
"""
import os
import sys
import json

_LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")
_translations = {}  # { "en": {"key": "string", ...}, "ru": {...} }
_current = "en"


def _config_path():
    """Путь к файлу конфигурации (рядом с exe или со скриптом)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "wi_config.json")


def get_dictionaries_dir() -> str:
    """Папка глобальных словарей (общая для всех проектов). Создаётся при первом использовании."""
    path = os.path.join(os.path.dirname(_config_path()), "dictionaries")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def save_locale_preference(code: str) -> None:
    """Сохранить выбранный язык интерфейса в конфиг."""
    code = (code or "en").strip().lower()
    path = _config_path()
    try:
        data = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["locale"] = code
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_locale_preference() -> str:
    """Загрузить сохранённый язык из конфига. Возвращает код или '' если нет/ошибка."""
    path = _config_path()
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return (data.get("locale") or "").strip().lower()
    except Exception:
        return ""


def load_config() -> dict:
    """Загрузить весь конфиг (locale, настройки транскрибации и т.д.)."""
    path = _config_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(updates: dict) -> None:
    """Обновить конфиг: слить updates с текущим и сохранить."""
    path = _config_path()
    data = load_config()
    data.update(updates)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


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
