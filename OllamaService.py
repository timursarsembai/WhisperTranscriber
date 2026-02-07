# -*- coding: utf-8 -*-
"""
Ollama Connect — интеграция с локальными LLM (Ollama) для коррекции текста.
"""

import json
import urllib.error
import urllib.request
from typing import List, Optional

DEFAULT_BASE_URL = "http://127.0.0.1:11434"


class OllamaService:
    """Проверка доступности Ollama и коррекция текста через API."""
    DEFAULT_MODEL = "llama3.2"

    def __init__(self, base_url: str = DEFAULT_BASE_URL):
        self.base_url = base_url.rstrip("/")
        self._last_error: Optional[str] = None

    def is_available(self) -> bool:
        """Проверяет, доступен ли Ollama (GET /api/tags или /api/version)."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=3) as r:
                return r.status == 200
        except Exception:
            return False

    def _list_models_full(self) -> List[str]:
        """Список моделей с тегом, как возвращает Ollama (например gemma3:latest)."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/api/tags",
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                data = json.loads(r.read().decode())
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except Exception:
            return []

    def list_models(self) -> List[str]:
        """Возвращает короткие имена моделей (без тега) для отображения."""
        return [n.split(":")[0] for n in self._list_models_full()]

    def get_effective_model(self) -> Optional[str]:
        """
        Возвращает полное имя модели для API (с тегом, например gemma3:latest).
        Приоритет: DEFAULT_MODEL, иначе первая доступная. None, если моделей нет.
        """
        full = self._list_models_full()
        if not full:
            return None
        for name in full:
            if name == self.DEFAULT_MODEL or name.startswith(self.DEFAULT_MODEL + ":"):
                return name
        return full[0]

    def get_last_error(self) -> Optional[str]:
        """Текст последней ошибки API (для отображения пользователю)."""
        return self._last_error

    def correct_text(
        self,
        text: str,
        model: str = None,
        system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """
        Отправляет текст на коррекцию. Возвращает исправленный текст или None при ошибке.
        system_prompt: опционально — контекст (например, глоссарий терминов).
        """
        if not (text or "").strip():
            return text
        if model is None:
            model = self.DEFAULT_MODEL

        prompt = f"""Correct the following transcription: fix only typos, punctuation, and grammar. Keep the EXACT SAME LANGUAGE as the input — do NOT translate. Preserve meaning and structure. Output ONLY the corrected text, no explanations.

Text to correct:
{text}"""

        system_instruction = "You are a transcription corrector. Only fix typos, punctuation, and grammar. Never translate: keep the exact same language as the input."
        if system_prompt and system_prompt.strip():
            system_instruction = system_instruction + "\n\n" + system_prompt.strip()
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "system": system_instruction,
        }

        self._last_error = None
        try:
            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/generate",
                data=data,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=120) as r:
                out = json.loads(r.read().decode())
            response = out.get("response", "").strip()
            return response if response else text
        except urllib.error.HTTPError as e:
            try:
                err_body = e.fp.read().decode() if e.fp else ""
                parsed = json.loads(err_body) if err_body.strip().startswith("{") else {}
                self._last_error = parsed.get("error", err_body) or f"{e.code} {e.reason}"
            except Exception:
                self._last_error = f"{e.code} {e.reason}"
            return None
        except Exception as e:
            self._last_error = str(e)
            return None

    def correct_segments(
        self,
        segments: List[dict],
        model: str = None,
        system_prompt: Optional[str] = None,
        progress_callback=None,
    ) -> Optional[List[dict]]:
        """
        Корректирует текст каждого сегмента (in-place не меняет, возвращает новый список).
        progress_callback(current_index, total, segment_text) — опционально для UI.
        """
        if model is None:
            model = self.DEFAULT_MODEL
        result = []
        total = len(segments)
        for i, seg in enumerate(segments):
            text = seg.get("text", "").strip()
            if not text:
                result.append(dict(seg))
                if progress_callback:
                    progress_callback(i + 1, total, text)
                continue
            corrected = self.correct_text(text, model=model, system_prompt=system_prompt)
            if corrected is None:
                # Ошибка API (например, модель не найдена) — прерываем, не спамим запросами
                return None
            else:
                new_seg = dict(seg)
                new_seg["text"] = corrected
                result.append(new_seg)
            if progress_callback:
                progress_callback(i + 1, total, corrected or text)
        return result
