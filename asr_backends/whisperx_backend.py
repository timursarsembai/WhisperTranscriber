# -*- coding: utf-8 -*-
"""
WhisperX backend: transcription + alignment + optional diarization.
Requires: whisperx (torch, transformers, faster-whisper). HF token needed for diarization.
"""
from typing import Any, List, Optional, Tuple

from asr_backends.base import ASRBackend


class WhisperXBackend(ASRBackend):
    """WhisperX: transcribe -> align -> optional diarize. Returns segments with optional speaker."""

    def __init__(self):
        self._model = None
        self.is_running = False

    @staticmethod
    def get_models_cache_dir() -> str:
        import sys
        import os
        if getattr(sys, "frozen", False):
            return os.path.join(os.path.dirname(sys.executable), "models")
        return os.path.join(os.getcwd(), "models")

    def load_model(
        self,
        model_size: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
        language: Optional[str] = None,
        **kwargs,
    ) -> bool:
        self._load_error = None
        try:
            from whisperx.asr import load_model as wx_load_model
        except ImportError:
            self._load_error = "WhisperX not installed. Install: pip install whisperx"
            print(self._load_error)
            return False

        model_dir = self.get_models_cache_dir()
        import os
        os.makedirs(model_dir, exist_ok=True)

        try:
            self._model = wx_load_model(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=model_dir,
                language=language if language and language != "auto" else None,
            )
            return True
        except Exception as e:
            self._load_error = str(e) or "WhisperX load error"
            print(f"WhisperX load error: {e}")
            return False

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
        diarize: bool = False,
        hf_token: Optional[str] = None,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        **kwargs,
    ) -> Tuple[List[dict], Any]:
        if not self._model:
            raise Exception("Model not loaded!")

        from whisperx import load_audio
        from whisperx.alignment import load_align_model, align
        from whisperx.diarize import DiarizationPipeline, assign_word_speakers

        self.is_running = True
        try:
            audio = load_audio(file_path)
            batch_size = 16
            result = self._model.transcribe(audio, batch_size=batch_size)

            if task == "translate":
                diarize = False

            if not diarize:
                segments = result.get("segments", [])
                out = []
                for s in segments:
                    out.append({
                        "start": s.get("start", 0),
                        "end": s.get("end", 0),
                        "text": (s.get("text") or "").strip(),
                    })
                    if progress_callback:
                        progress_callback(s.get("end", 0), result.get("duration") or 0, (s.get("text") or "").strip())
                self.is_running = False
                class Info:
                    duration = result.get("duration") or 0
                return out, Info()

            lang = result.get("language") or (language if language and language != "auto" else "en")
            align_model, align_metadata = load_align_model(lang, "cuda")
            if align_model and result.get("segments"):
                result = align(
                    result["segments"],
                    align_model,
                    align_metadata,
                    file_path,
                    "cuda",
                )

            diarize_model = DiarizationPipeline(use_auth_token=hf_token or None, device="cuda")
            diarize_segments = diarize_model(
                file_path,
                min_speakers=min_speakers,
                max_speakers=max_speakers,
            )
            result = assign_word_speakers(diarize_segments, result)

            out = []
            duration = 0
            for s in result.get("segments", []):
                duration = max(duration, s.get("end", 0))
                seg = {
                    "start": s.get("start", 0),
                    "end": s.get("end", 0),
                    "text": (s.get("text") or "").strip(),
                }
                if s.get("speaker") is not None:
                    seg["speaker"] = str(s["speaker"])
                out.append(seg)
                if progress_callback:
                    progress_callback(s.get("end", 0), duration, (s.get("text") or "").strip())

            self.is_running = False
            class Info:
                duration = duration
            return out, Info()

        except Exception as e:
            self.is_running = False
            raise

    def stop(self) -> None:
        self.is_running = False
