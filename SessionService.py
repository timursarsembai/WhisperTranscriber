# -*- coding: utf-8 -*-
"""
Session System — единый источник истины для проекта транскрибации.
Файл .wiproject хранит: пути к аудио, транскрипт с таймлайнами, историю правок, ссылку на глоссарий.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

# Версия схемы для обратной совместимости при изменении формата
SCHEMA_VERSION = 1
SCHEMA_VERSION_MULTI_FILE = 2


@dataclass
class SessionData:
    """Данные сессии проекта (.wiproject)."""

    # Путь к аудио/видео (в файле хранится относительный к папке .wiproject для переносимости)
    # В v2 используется вместе с file_transcripts; при загрузке v1 сюда подставляется единственный файл
    audio_path: str = ""
    # Текущий транскрипт: список сегментов с таймлайнами (v1 или текущий файл в v2)
    transcript: List[dict] = field(default_factory=list)  # [{"start": float, "end": float, "text": str}, ...]
    # Метаданные
    created_at: str = ""
    updated_at: str = ""
    model_used: str = ""
    # Для будущего: история правок (снимки или диффы)
    edit_history: List[dict] = field(default_factory=list)
    # Путь к глоссарию (JSON), опционально (legacy)
    glossary_path: Optional[str] = None
    # Включённые глобальные словари (ID = имена файлов в папке dictionaries)
    enabled_dictionary_ids: Optional[List[str]] = None
    # Версия схемы
    version: int = SCHEMA_VERSION
    # v2: транскрипты по всем файлам (ключ — относительный путь от папки проекта)
    file_transcripts: Optional[Dict[str, List[dict]]] = None
    # v2: относительный путь текущего выбранного файла
    current_file_rel: Optional[str] = None

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat() + "Z"
        if not self.updated_at:
            self.updated_at = self.created_at

    def to_dict(self) -> dict:
        d = asdict(self)
        # Не сохраняем None в JSON для опциональных полей v2 — пишем только если есть данные
        if d.get("file_transcripts") is None:
            d.pop("file_transcripts", None)
        if d.get("current_file_rel") is None:
            d.pop("current_file_rel", None)
        if d.get("enabled_dictionary_ids") is None:
            d.pop("enabled_dictionary_ids", None)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SessionData":
        known = {
            "audio_path", "transcript", "created_at", "updated_at",
            "model_used", "edit_history", "glossary_path", "enabled_dictionary_ids", "version",
            "file_transcripts", "current_file_rel",
        }
        filtered = {k: v for k, v in data.items() if k in known}
        if "transcript" not in filtered:
            filtered["transcript"] = []
        if "audio_path" not in filtered:
            filtered["audio_path"] = ""
        # Обратная совместимость: старый формат (v1) — один audio_path + transcript
        if not filtered.get("file_transcripts") and filtered.get("audio_path"):
            # v1: строим file_transcripts из единственного файла (rel path заполним при load_session)
            pass
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
        v2: пишем file_transcripts (ключи — относительные пути) и current_file (относительный).
        v1-совместимость: если передан старый session с audio_path/transcript, сохраняем как v2 с одним файлом.
        """
        try:
            session.updated_at = datetime.utcnow().isoformat() + "Z"
            payload = session.to_dict()
            payload["version"] = SCHEMA_VERSION_MULTI_FILE
            # v2: file_transcripts и current_file_rel уже в payload если заданы
            if session.file_transcripts is not None:
                payload["file_transcripts"] = session.file_transcripts
                payload["current_file"] = session.current_file_rel or ""
            else:
                # Сохранение из старого формата или единственного файла: один ключ в file_transcripts
                rel = SessionService._make_path_relative_to_project(
                    session.audio_path, project_path
                )
                payload["file_transcripts"] = {rel: list(session.transcript)}
                payload["current_file"] = rel
            # Для обратной совместимости читателей v1 оставляем audio_path и transcript
            payload["audio_path"] = SessionService._make_path_relative_to_project(
                session.audio_path, project_path
            )
            if "transcript" not in payload or payload["transcript"] is None:
                payload["transcript"] = session.transcript
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
        v2: заполняет file_transcripts (ключи остаются относительными), current_file_rel, audio_path = абсолютный текущий файл.
        v1: file_transcripts = { relpath(audio_path): transcript }, current_file_rel = relpath(audio_path).
        """
        try:
            with open(project_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # v2: в файле могут быть "file_transcripts" и "current_file" (в JSON ключ current_file)
            file_transcripts = data.get("file_transcripts")
            current_file_rel = data.get("current_file")
            if file_transcripts is None and data.get("audio_path"):
                # v1: один файл; в файле audio_path уже относительный
                rel = data["audio_path"]
                file_transcripts = {rel: data.get("transcript", [])}
                current_file_rel = rel
            session = SessionData.from_dict(data)
            session.file_transcripts = file_transcripts or {}
            session.current_file_rel = current_file_rel or None
            # Текущий аудио-путь (абсолютный) и транскрипт текущего файла
            project_dir = os.path.dirname(os.path.abspath(project_path))
            if session.current_file_rel:
                session.audio_path = os.path.normpath(
                    os.path.join(project_dir, session.current_file_rel)
                )
                session.transcript = list(
                    session.file_transcripts.get(session.current_file_rel, [])
                )
            else:
                # Fallback: первый файл из file_transcripts или старый audio_path
                if session.file_transcripts:
                    first_rel = next(iter(session.file_transcripts))
                    session.current_file_rel = first_rel
                    session.audio_path = os.path.normpath(
                        os.path.join(project_dir, first_rel)
                    )
                    session.transcript = list(session.file_transcripts[first_rel])
                elif session.audio_path:
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
        enabled_dictionary_ids: Optional[List[str]] = None,
        project_path: Optional[str] = None,
        file_transcripts: Optional[Dict[str, List[dict]]] = None,
        current_file_rel: Optional[str] = None,
    ) -> SessionData:
        """Собирает SessionData из текущего состояния приложения.
        Если заданы project_path, file_transcripts и current_file_rel — сохраняем в формате v2."""
        s = SessionData(
            audio_path=audio_path,
            transcript=list(transcript),
            model_used=model_used,
            glossary_path=glossary_path,
            enabled_dictionary_ids=enabled_dictionary_ids or None,
        )
        if project_path is not None and file_transcripts is not None:
            s.file_transcripts = dict(file_transcripts)
            s.current_file_rel = current_file_rel or (
                SessionService._make_path_relative_to_project(audio_path, project_path)
                if audio_path else None
            )
        return s
