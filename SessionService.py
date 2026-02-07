# -*- coding: utf-8 -*-
"""
Session System — единый источник истины для проекта транскрибации.
Файл .wiproject хранит: пути к аудио, транскрипт с таймлайнами, историю правок, ссылку на глоссарий.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List, Optional

# Версия схемы для обратной совместимости при изменении формата
SCHEMA_VERSION = 1


@dataclass
class SessionData:
    """Данные сессии проекта (.wiproject)."""

    # Путь к аудио/видео (в файле хранится относительный к папке .wiproject для переносимости)
    audio_path: str
    # Текущий транскрипт: список сегментов с таймлайнами
    transcript: List[dict]  # [{"start": float, "end": float, "text": str}, ...]
    # Метаданные
    created_at: str = ""
    updated_at: str = ""
    model_used: str = ""
    # Для будущего: история правок (снимки или диффы)
    edit_history: List[dict] = field(default_factory=list)
    # Путь к глоссарию (JSON), опционально
    glossary_path: Optional[str] = None
    # Версия схемы
    version: int = SCHEMA_VERSION

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat() + "Z"
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SessionData":
        # Игнорируем лишние поля для совместимости с будущими версиями
        known = {
            "audio_path", "transcript", "created_at", "updated_at",
            "model_used", "edit_history", "glossary_path", "version"
        }
        filtered = {k: v for k, v in data.items() if k in known}
        if "transcript" not in filtered:
            filtered["transcript"] = []
        return cls(**filtered)


class SessionService:
    """Сохранение и загрузка сессии в файл .wiproject (JSON)."""

    @staticmethod
    def _make_path_relative_to_project(audio_path: str, project_path: str) -> str:
        """Возвращает путь к аудио относительно папки, в которой лежит .wiproject."""
        project_dir = os.path.dirname(os.path.abspath(project_path))
        try:
            return os.path.relpath(os.path.abspath(audio_path), project_dir)
        except ValueError:
            # Разные диски (Windows) — оставляем абсолютный
            return os.path.abspath(audio_path)

    @staticmethod
    def _resolve_audio_path(stored_path: str, project_path: str) -> str:
        """Преобразует сохранённый (относительный или абсолютный) путь в абсолютный."""
        if os.path.isabs(stored_path) and os.path.exists(stored_path):
            return stored_path
        project_dir = os.path.dirname(os.path.abspath(project_path))
        resolved = os.path.normpath(os.path.join(project_dir, stored_path))
        return resolved

    @staticmethod
    def save_session(project_path: str, session: SessionData) -> bool:
        """
        Сохраняет сессию в файл .wiproject (JSON).
        audio_path в файле сохраняется относительно папки проекта.
        """
        try:
            session.updated_at = datetime.utcnow().isoformat() + "Z"
            payload = session.to_dict()
            # В файл пишем относительный путь к аудио
            payload["audio_path"] = SessionService._make_path_relative_to_project(
                session.audio_path, project_path
            )
            with open(project_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            return True
        except Exception as e:
            print(f"Session save error: {e}")
            return False

    @staticmethod
    def load_session(project_path: str) -> Optional[SessionData]:
        """
        Загружает сессию из файла .wiproject.
        Возвращает SessionData с уже разрешённым абсолютным путём к аудио, или None при ошибке.
        """
        try:
            with open(project_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = SessionData.from_dict(data)
            # Разрешаем путь к аудио относительно папки проекта
            session.audio_path = SessionService._resolve_audio_path(
                session.audio_path, project_path
            )
            return session
        except Exception as e:
            print(f"Session load error: {e}")
            return None

    @staticmethod
    def build_session(
        audio_path: str,
        transcript: List[dict],
        model_used: str = "",
        glossary_path: Optional[str] = None,
    ) -> SessionData:
        """Собирает SessionData из текущего состояния приложения."""
        return SessionData(
            audio_path=audio_path,
            transcript=list(transcript),
            model_used=model_used,
            glossary_path=glossary_path,
        )
