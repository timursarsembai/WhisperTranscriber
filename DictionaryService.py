# -*- coding: utf-8 -*-
"""
Dictionary Service — глобальные словари с типами correction/terms.
Один формат файла с полем type; формирование initial_prompt и постобработка исправлений.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

DICTIONARY_SCHEMA_VERSION = 1
TYPE_CORRECTION = "correction"
TYPE_TERMS = "terms"


@dataclass
class DictionaryEntry:
    """Одна запись: для correction — original/corrected; для terms — term (или original==corrected)."""

    original: str = ""
    corrected: str = ""
    term: str = ""  # для type=terms

    def to_dict(self, dict_type: str) -> dict:
        if dict_type == TYPE_TERMS:
            return {"term": self.term or self.original or self.corrected}
        return {"original": self.original, "corrected": self.corrected}

    @classmethod
    def from_dict(cls, data: dict, dict_type: str) -> "DictionaryEntry":
        if dict_type == TYPE_TERMS:
            term = (data.get("term") or data.get("original") or data.get("corrected") or "").strip()
            return cls(original=term, corrected=term, term=term)
        return cls(
            original=(data.get("original") or "").strip(),
            corrected=(data.get("corrected") or "").strip(),
        )


@dataclass
class DictionaryData:
    """Данные одного словаря: тип, имя, записи."""

    type: str = TYPE_CORRECTION  # "correction" | "terms"
    name: str = ""
    entries: List[DictionaryEntry] = field(default_factory=list)
    version: int = DICTIONARY_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "type": self.type,
            "name": self.name,
            "entries": [e.to_dict(self.type) for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DictionaryData":
        dtype = (data.get("type") or TYPE_CORRECTION).strip().lower()
        if dtype not in (TYPE_CORRECTION, TYPE_TERMS):
            dtype = TYPE_CORRECTION
        entries = []
        for item in data.get("entries", []):
            if isinstance(item, dict):
                entries.append(DictionaryEntry.from_dict(item, dtype))
        return cls(
            type=dtype,
            name=(data.get("name") or "").strip(),
            entries=entries,
            version=data.get("version", DICTIONARY_SCHEMA_VERSION),
        )


def _get_dictionaries_dir() -> str:
    from i18n import get_dictionaries_dir
    return get_dictionaries_dir()


class DictionaryService:
    """Глобальные словари: список, загрузка, сохранение, prompt и постобработка."""

    @staticmethod
    def get_dictionaries_dir() -> str:
        return _get_dictionaries_dir()

    @staticmethod
    def list_dictionaries() -> List[Dict[str, Any]]:
        """Список словарей в глобальной папке. Возвращает [{"id": "file.json", "path": abs, "name", "type"}, ...]."""
        result = []
        base = DictionaryService.get_dictionaries_dir()
        if not os.path.isdir(base):
            return result
        for fname in sorted(os.listdir(base)):
            if not (fname.endswith(".json") or fname.endswith(".widict")):
                continue
            path = os.path.join(base, fname)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                dtype = (data.get("type") or TYPE_CORRECTION).strip().lower()
                if dtype not in (TYPE_CORRECTION, TYPE_TERMS):
                    dtype = TYPE_CORRECTION
                result.append({
                    "id": fname,
                    "path": os.path.abspath(path),
                    "name": (data.get("name") or fname).strip(),
                    "type": dtype,
                })
            except Exception:
                result.append({"id": fname, "path": os.path.abspath(path), "name": fname, "type": TYPE_CORRECTION})
        return result

    @staticmethod
    def load(path: str) -> Optional[DictionaryData]:
        """Загружает словарь из файла. Файлы без поля type считаются correction (старый глоссарий)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return DictionaryData.from_dict(data)
        except Exception as e:
            print(f"Dictionary load error: {e}")
            return None

    @staticmethod
    def load_by_id(dict_id: str) -> Optional[DictionaryData]:
        """Загружает словарь по ID (имя файла) из глобальной папки."""
        base = DictionaryService.get_dictionaries_dir()
        path = os.path.join(base, dict_id)
        if not os.path.isfile(path):
            return None
        return DictionaryService.load(path)

    @staticmethod
    def save(path: str, data: DictionaryData) -> bool:
        """Сохраняет словарь в файл."""
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Dictionary save error: {e}")
            return False

    @staticmethod
    def build_initial_prompt_text(dictionaries: List[DictionaryData]) -> str:
        """
        Объединяет terms и correction из списка словарей в один текст для Whisper initial_prompt.
        """
        terms_lines = []
        correction_lines = []
        for d in dictionaries:
            if not d.entries:
                continue
            if d.type == TYPE_TERMS:
                for e in d.entries:
                    t = (e.term or e.original or e.corrected or "").strip()
                    if t:
                        terms_lines.append(t)
            else:
                for e in d.entries:
                    if (e.original or "").strip() and (e.corrected or "").strip():
                        correction_lines.append(f"  {e.original} -> {e.corrected}")
        parts = []
        if terms_lines:
            parts.append("Use these terms as written: " + ", ".join(terms_lines))
        if correction_lines:
            parts.append("Use these terms as written:")
            parts.extend(correction_lines)
        return "\n".join(parts) if parts else ""

    @staticmethod
    def apply_corrections_to_segments(
        segments: List[dict],
        correction_entries: List[Dict[str, str]],
    ) -> None:
        """
        Заменяет в segment["text"] вхождения original на corrected (in-place).
        correction_entries: [{"original": "...", "corrected": "..."}, ...]
        """
        for seg in segments:
            text = seg.get("text") or ""
            for entry in correction_entries:
                orig = entry.get("original") or ""
                corr = entry.get("corrected") or ""
                if orig and orig in text:
                    text = text.replace(orig, corr)
            seg["text"] = text

    @staticmethod
    def get_correction_entries_from_dictionaries(dictionaries: List[DictionaryData]) -> List[Dict[str, str]]:
        """Собирает все пары original/corrected из словарей типа correction."""
        out = []
        for d in dictionaries:
            if d.type != TYPE_CORRECTION:
                continue
            for e in d.entries:
                if (e.original or "").strip() and (e.corrected or "").strip():
                    out.append({"original": e.original, "corrected": e.corrected})
        return out
