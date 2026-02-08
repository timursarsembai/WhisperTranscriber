# -*- coding: utf-8 -*-
"""
Whisper-Streaming (ufal) backend for low-latency streaming transcription.
Requires: whisper-streaming (or ufal/whisper_streaming), librosa, soundfile.
Audio must be 16 kHz mono float32 for insert_audio_chunk.
"""
import subprocess
import sys
from typing import Any, Iterator, List, Optional, Tuple

from asr_backends.base import ASRBackend


def _ensure_whisper_streaming_installed() -> tuple[bool, str | None]:
    """If running from source (not frozen EXE), install whisper-streaming and librosa once.
    Returns (True, None) on success, (False, error_message) on failure."""
    if getattr(sys, "frozen", False):
        return False, None
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "whisper-streaming", "librosa"],
            capture_output=True,
            timeout=300,
            text=True,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout or "").strip()
            if len(err) > 500:
                err = err[:497] + "..."
            return False, err or f"pip exit code {r.returncode}"
        return True, None
    except FileNotFoundError:
        return False, "pip not found (Python environment issue)."
    except subprocess.TimeoutExpired:
        return False, "Installation timed out."
    except Exception as e:
        return False, str(e) or type(e).__name__


class WhisperStreamingBackend(ASRBackend):
    """Streaming backend using ufal/whisper_streaming. For microphone only."""

    def __init__(self):
        self._asr = None
        self._online = None
        self._model_size = "base"
        self._language = "auto"
        self._task = "transcribe"
        self._vad = False
        self._cache_dir = None
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
        model_size: str = "base",
        device: str = "cuda",
        compute_type: str = "float16",
        language: Optional[str] = None,
        task: str = "transcribe",
        vad_filter: bool = False,
        **kwargs,
    ) -> bool:
        self._load_error = None
        # Whisper-Streaming on PyPI supports only Python 3.9–3.12; avoid useless pip run on 3.13
        if sys.version_info >= (3, 13):
            self._load_error = (
                "Whisper-Streaming не поддерживает Python 3.13. Нужен Python 3.9–3.12. "
                "Запустите приложение в окружении Python 3.12 (например: py -3.12 main.py или виртуальное окружение с 3.12). "
                "Остальные функции приложения (транскрибация файлов, импорт и т.д.) работают нормально."
            )
            return False
        asr_classes = None
        try:
            from whisper_online import FasterWhisperASR, OnlineASRProcessor
            asr_classes = (FasterWhisperASR, OnlineASRProcessor)
        except ImportError:
            try:
                from whisper_streaming.whisper_online import FasterWhisperASR, OnlineASRProcessor
                asr_classes = (FasterWhisperASR, OnlineASRProcessor)
            except ImportError:
                pass
        install_error: str | None = None
        if asr_classes is None and not getattr(sys, "frozen", False):
            _ok, install_error = _ensure_whisper_streaming_installed()
            last_import_error: str | None = None
            try:
                from whisper_online import FasterWhisperASR, OnlineASRProcessor
                asr_classes = (FasterWhisperASR, OnlineASRProcessor)
            except ImportError as e:
                last_import_error = str(e) or e.msg
                try:
                    from whisper_streaming.whisper_online import FasterWhisperASR, OnlineASRProcessor
                    asr_classes = (FasterWhisperASR, OnlineASRProcessor)
                except ImportError as e2:
                    last_import_error = str(e2) or getattr(e2, "msg", None) or "unknown"
            if asr_classes is None and last_import_error:
                install_error = (install_error or "").strip() or last_import_error
        if asr_classes is None:
            if getattr(sys, "frozen", False):
                self._load_error = "Whisper-Streaming is not included in this build. Use the full installer."
            else:
                err_lower = (install_error or "").lower()
                py313_incompat = (
                    "requires-python" in err_lower
                    and "3.13" in (install_error or "")
                    and ("could not find a version" in err_lower or "from versions: none" in err_lower)
                )
                if py313_incompat:
                    self._load_error = (
                        "Whisper-Streaming не поддерживает Python 3.13. Нужен Python 3.9–3.12. "
                        "Запустите приложение в окружении Python 3.12 (например: py -3.12 main.py или виртуальное окружение с 3.12). "
                        "Остальные функции приложения (транскрибация файлов, импорт и т.д.) работают нормально."
                    )
                else:
                    self._load_error = "Whisper-Streaming could not be installed."
                    if install_error:
                        self._load_error += " " + (install_error[:400] + "..." if len(install_error) > 400 else install_error)
                    else:
                        self._load_error += " Install: pip install whisper-streaming librosa"
            return False
        FasterWhisperASR, OnlineASRProcessor = asr_classes[0], asr_classes[1]

        self._model_size = model_size or "base"
        self._language = (language or "auto").strip() if language else "auto"
        self._task = (task or "transcribe").strip()
        self._vad = vad_filter
        self._cache_dir = self.get_models_cache_dir()

        try:
            import os
            os.makedirs(self._cache_dir, exist_ok=True)
            self._asr = FasterWhisperASR(
                lan=self._language,
                modelsize=self._model_size,
                cache_dir=self._cache_dir,
            )
            if self._vad:
                self._asr.use_vad()
            if self._task == "translate":
                self._asr.set_translate_task()
            self._online = OnlineASRProcessor(
                self._asr,
                tokenizer=None,
                buffer_trimming=("segment", 15),
            )
            return True
        except Exception as e:
            self._load_error = str(e) or "WhisperStreaming load error"
            print(f"WhisperStreaming load error: {e}")
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
        **kwargs,
    ) -> Tuple[List[dict], Any]:
        """Streaming backend: transcribe file by simulating stream (read file, feed chunks)."""
        if not self._online or not self._asr:
            raise Exception("Model not loaded!")

        try:
            import numpy as np
            import librosa
        except ImportError:
            raise Exception("librosa required for WhisperStreaming file transcription")

        self.is_running = True
        audio, sr = librosa.load(file_path, sr=16000, dtype=np.float32)
        if sr != 16000:
            audio = librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=16000)

        self._online.init()
        min_chunk = int(1.0 * 16000)  # 1 second
        segments_out = []
        offset = 0.0
        i = 0
        duration_sec = len(audio) / 16000.0

        while i < len(audio) and self.is_running:
            chunk = audio[i:i + min_chunk]
            if len(chunk) == 0:
                break
            self._online.insert_audio_chunk(chunk)
            result = self._online.process_iter()
            beg, end, text = result
            if beg is not None and end is not None and (text or "").strip():
                segments_out.append({
                    "start": offset + beg,
                    "end": offset + end,
                    "text": (text or "").strip(),
                })
                if progress_callback:
                    progress_callback(offset + end, duration_sec, (text or "").strip())
            i += len(chunk)

        last = self._online.finish()
        beg, end, text = last
        if beg is not None and end is not None and (text or "").strip():
            segments_out.append({
                "start": offset + beg,
                "end": offset + end,
                "text": (text or "").strip(),
            })

        self.is_running = False
        class Info:
            duration = duration_sec
        return segments_out, Info()

    def stop(self) -> None:
        self.is_running = False

    def supports_streaming(self) -> bool:
        return True

    def streaming_transcribe(
        self,
        chunk_iterator: Iterator[Tuple[Any, int]],
        **kwargs,
    ) -> Iterator[Tuple[float, float, str]]:
        """
        Yield (start, end, text) for each confirmed segment.
        chunk_iterator yields (audio_float32_16k, sample_rate) or (audio_float32_16k,).
        """
        if not self._online:
            return
        try:
            import numpy as np
            import librosa
        except ImportError:
            return

        self._online.init()
        for item in chunk_iterator:
            if not self.is_running:
                break
            if isinstance(item, (tuple, list)):
                if len(item) >= 2:
                    audio, sr = item[0], item[1]
                else:
                    audio = item[0]
                    sr = 16000
            else:
                audio = item
                sr = 16000

            if hasattr(audio, "dtype") and audio.dtype != np.float32:
                audio = audio.astype(np.float32)
            if sr != 16000:
                audio = librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=16000)

            self._online.insert_audio_chunk(audio)
            result = self._online.process_iter()
            beg, end, text = result
            if beg is not None and end is not None and (text or "").strip():
                yield (beg, end, (text or "").strip())

        last = self._online.finish()
        beg, end, text = last
        if beg is not None and end is not None and (text or "").strip():
            yield (beg, end, (text or "").strip())
