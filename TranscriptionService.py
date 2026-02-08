# -*- coding: utf-8 -*-
"""
TranscriptionService: facade over ASR backends.
Selects backend by config key transcription_engine: "faster-whisper" | "whisper-streaming" | "whisperx".
"""
import os
import sys
from typing import Optional

# Avoid circular import: load_config is used lazily in get_backend
def _load_config():
    from i18n import load_config
    return load_config()


def _get_backend_class(engine: str):
    if engine == "faster-whisper":
        from asr_backends.faster_whisper_backend import FasterWhisperBackend
        return FasterWhisperBackend
    if engine == "whisper-streaming":
        from asr_backends.whisper_streaming_backend import WhisperStreamingBackend
        return WhisperStreamingBackend
    if engine == "whisperx":
        from asr_backends.whisperx_backend import WhisperXBackend
        return WhisperXBackend
    from asr_backends.faster_whisper_backend import FasterWhisperBackend
    return FasterWhisperBackend


class TranscriptionService:
    def __init__(self):
        self._backend = None
        self._engine = None
        self._engine_override = None  # e.g. "whisper-streaming" for mic streaming

    def _get_backend(self):
        cfg = _load_config()
        engine = self._engine_override or (cfg.get("transcription_engine") or "faster-whisper").strip().lower()
        if engine not in ("faster-whisper", "whisper-streaming", "whisperx"):
            engine = "faster-whisper"
        if self._backend is None or self._engine != engine:
            self._engine = engine
            cls = _get_backend_class(engine)
            self._backend = cls()
        return self._backend

    def set_engine_override(self, engine: Optional[str]):
        """Временно использовать указанный движок (например для потока с микрофона). None — сброс."""
        if engine != self._engine_override:
            self._engine_override = engine
            self._backend = None
            self._engine = None

    def clear_engine_override(self):
        """Сбросить временный движок (после остановки потока)."""
        self.set_engine_override(None)

    @property
    def model(self):
        """For compatibility: main.py may set service.model = None to unload."""
        be = self._backend
        if be is None:
            return None
        return getattr(be, "model", None)

    @model.setter
    def model(self, value):
        if value is None and self._backend is not None:
            self._backend = None
            self._engine = None

    @staticmethod
    def get_models_cache_dir() -> str:
        if getattr(sys, "frozen", False):
            return os.path.join(os.path.dirname(sys.executable), "models")
        return os.path.join(os.getcwd(), "models")

    def load_model(self, model_size="large-v3", device="cuda", compute_type="float16", engine_override=None, **kwargs):
        if engine_override is not None:
            self.set_engine_override(engine_override)
        kwargs = {k: v for k, v in kwargs.items() if k != "engine_override"}
        backend = self._get_backend()
        self._last_load_error = None
        ok = backend.load_model(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            **kwargs,
        )
        if not ok:
            self._last_load_error = getattr(backend, "_load_error", None) or "Failed to load model."
        return ok

    def transcribe(
        self,
        file_path,
        language=None,
        initial_prompt=None,
        beam_size=5,
        vad_filter=True,
        task="transcribe",
        word_timestamps=False,
        progress_callback=None,
        **kwargs,
    ):
        backend = self._get_backend()
        return backend.transcribe(
            file_path,
            language=language,
            initial_prompt=initial_prompt,
            beam_size=beam_size,
            vad_filter=vad_filter,
            task=task,
            word_timestamps=word_timestamps,
            progress_callback=progress_callback,
            **kwargs,
        )

    def stop(self):
        if self._backend is not None:
            self._backend.stop()

    @property
    def is_running(self):
        if self._backend is None:
            return False
        return getattr(self._backend, "is_running", False)

    def supports_streaming(self):
        if self._backend is None:
            return False
        return getattr(self._backend, "supports_streaming", lambda: False)()

    def streaming_transcribe(self, chunk_iterator, **kwargs):
        """For microphone: yield (start, end, text) from streaming backend."""
        backend = self._get_backend()
        if not getattr(backend, "supports_streaming", lambda: False)():
            raise NotImplementedError("Current engine does not support streaming")
        return backend.streaming_transcribe(chunk_iterator, **kwargs)
