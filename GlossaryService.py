# -*- coding: utf-8 -*-
"""
Core Glossary — хранилище пар «Было -> Стало» в JSON.
Используется для обучения на правках пользователя и как Initial Prompt для Whisper.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional

GLOSSARY_SCHEMA_VERSION = 1


@dataclass
class GlossaryEntry:
    """Одна запись глоссария: оригинал (как распознано) -> исправление."""

    original: str
    corrected: str
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat() + "Z"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "GlossaryEntry":
        known = {"original", "corrected", "created_at"}
        filtered = {k: v for k, v in data.items() if k in known}
        filtered.setdefault("original", "")
        filtered.setdefault("corrected", "")
        return cls(**filtered)


@dataclass
class GlossaryData:
    """Данные файла глоссария (.wiglossary или .json)."""

    entries: List[GlossaryEntry] = field(default_factory=list)
    version: int = GLOSSARY_SCHEMA_VERSION

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "entries": [e.to_dict() for e in self.entries],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GlossaryData":
        entries = []
        for item in data.get("entries", []):
            if isinstance(item, dict):
                entries.append(GlossaryEntry.from_dict(item))
        return cls(entries=entries, version=data.get("version", 1))


class GlossaryService:
    """Загрузка, сохранение и управление глоссарием в JSON."""

    @staticmethod
    def load(path: str) -> Optional[GlossaryData]:
        """Загружает глоссарий из JSON-файла."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return GlossaryData.from_dict(data)
        except Exception as e:
            print(f"Glossary load error: {e}")
            return None

    @staticmethod
    def save(path: str, glossary: GlossaryData) -> bool:
        """Сохраняет глоссарий в JSON-файл."""
        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(glossary.to_dict(), f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Glossary save error: {e}")
            return False

    @staticmethod
    def add_entry(glossary: GlossaryData, original: str, corrected: str) -> GlossaryData:
        """Добавляет или обновляет запись (по ключу original). Возвращает новый GlossaryData."""
        original = (original or "").strip()
        corrected = (corrected or "").strip()
        if not original:
            return glossary
        new_entries = [e for e in glossary.entries if e.original != original]
        new_entries.append(GlossaryEntry(original=original, corrected=corrected))
        return GlossaryData(entries=new_entries, version=glossary.version)

    @staticmethod
    def remove_entry(glossary: GlossaryData, original: str) -> GlossaryData:
        """Удаляет запись по оригиналу. Возвращает новый GlossaryData."""
        new_entries = [e for e in glossary.entries if e.original != original]
        return GlossaryData(entries=new_entries, version=glossary.version)

    @staticmethod
    def get_initial_prompt_text(glossary: GlossaryData) -> str:
        """
        Формирует текст «шпаргалки» для Whisper (initial_prompt / word timestamps).
        Используйте при вызове transcribe() для улучшения распознавания терминов.
        """
        if not glossary.entries:
            return ""
        lines = ["Use these terms as written:"]
        for e in glossary.entries:
            if e.original and e.corrected:
                lines.append(f"  {e.original} -> {e.corrected}")
        return "\n".join(lines)
