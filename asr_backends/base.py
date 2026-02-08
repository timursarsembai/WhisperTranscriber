# -*- coding: utf-8 -*-
"""
Base contract for ASR backends.
All backends return segments as list[dict] with keys: start, end, text; optional: speaker.
"""
from abc import ABC, abstractmethod
from typing import Any, List, Optional, Tuple


class ASRBackend(ABC):
    """Abstract ASR backend. load_model and transcribe must be implemented."""

    @abstractmethod
    def load_model(self, **kwargs) -> bool:
        """Load the model. Returns True on success."""
        pass

    @abstractmethod
    def transcribe(
        self,
        file_path: str,
        *,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        beam_size: int = 5,
        vad_filter: bool = True,
        task: str = "transcribe",
        word_timestamps: bool = False,
        progress_callback: Optional[Any] = None,
        **kwargs,
    ) -> Tuple[List[dict], Any]:
        """
        Transcribe file. Returns (segments, info).
        segments: list of {"start": float, "end": float, "text": str, "speaker"?: str}
        info: object with at least .duration (for compatibility).
        """
        pass

    def stop(self) -> None:
        """Stop current transcription if running."""
        pass

    def supports_streaming(self) -> bool:
        """True if this backend supports streaming (chunk-by-chunk) for microphone."""
        return False

    def streaming_transcribe(self, chunk_iterator, **kwargs):
        """
        If supports_streaming(): yield segments as they become available.
        chunk_iterator yields (audio_float_array_16k_mono, sample_rate) or (audio_float_array_16k_mono,).
        """
        raise NotImplementedError("Streaming not supported")
