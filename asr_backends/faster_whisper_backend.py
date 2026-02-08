# -*- coding: utf-8 -*-
"""
Faster-whisper ASR backend. Same behaviour as original TranscriptionService.
"""
import os
import sys
from typing import Any, List, Optional, Tuple

from asr_backends.base import ASRBackend


class FasterWhisperBackend(ASRBackend):
    """Backend using faster_whisper.WhisperModel."""

    def __init__(self):
        self.model = None
        self.is_running = False
        self._setup_dlls()

    def _setup_dlls(self) -> None:
        """Setup CUDA DLL paths for correct operation on Windows."""
        if getattr(sys, "frozen", False):
            base_path = sys._MEIPASS
            bundled_cublas = os.path.join(base_path, "nvidia", "cublas", "bin")
            bundled_cudnn = os.path.join(base_path, "nvidia", "cudnn", "bin")
            for p in [bundled_cublas, bundled_cudnn]:
                if os.path.exists(p):
                    os.add_dll_directory(p)
            return

        user_cublas = r"C:\Users\Timsar\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\nvidia\cublas\bin"
        user_cudnn = r"C:\Users\Timsar\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\nvidia\cudnn\bin"
        try:
            import nvidia.cublas
            import nvidia.cudnn
            pkg_cublas = os.path.join(nvidia.cublas.__path__[0], "bin")
            pkg_cudnn = os.path.join(nvidia.cudnn.__path__[0], "bin")
        except (ImportError, AttributeError, IndexError):
            pkg_cublas = pkg_cudnn = None

        paths_to_check = [user_cublas, user_cudnn, pkg_cublas, pkg_cudnn]
        for path in paths_to_check:
            if path and os.path.exists(path):
                try:
                    os.add_dll_directory(path)
                except Exception as e:
                    print(f"Ошибка при добавлении DLL пути {path}: {e}")

    @staticmethod
    def get_models_cache_dir() -> str:
        if getattr(sys, "frozen", False):
            return os.path.join(os.path.dirname(sys.executable), "models")
        return os.path.join(os.getcwd(), "models")

    def load_model(
        self,
        model_size: str = "large-v3",
        device: str = "cuda",
        compute_type: str = "float16",
        **kwargs,
    ) -> bool:
        self._load_error = None
        from faster_whisper import WhisperModel

        try:
            models_dir = self.get_models_cache_dir()
            if not os.path.exists(models_dir):
                os.makedirs(models_dir)
            if device == "cpu":
                compute_type = "int8" if compute_type == "float16" else compute_type
            self.model = WhisperModel(
                model_size,
                device=device,
                compute_type=compute_type,
                download_root=models_dir,
            )
            return True
        except Exception as e:
            self._load_error = str(e)
            print(f"Error loading model: {e}")
            if device == "cuda":
                print("Trying to switch to CPU...")
                try:
                    self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
                    return True
                except Exception as e2:
                    self._load_error = str(e2)
                    print(f"Error loading on CPU: {e2}")
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
        if not self.model:
            raise Exception("Model not loaded!")

        self.is_running = True
        opts = dict(
            beam_size=beam_size,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            task=task,
        )
        if initial_prompt and initial_prompt.strip():
            opts["initial_prompt"] = initial_prompt.strip()
        if language and language != "auto" and language.strip():
            opts["language"] = language.strip()

        segments, info = self.model.transcribe(file_path, **opts)

        full_results = []
        duration = getattr(info, "duration", 0)

        for segment in segments:
            if not self.is_running:
                break
            full_results.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
            })
            if progress_callback:
                progress_callback(segment.end, duration, segment.text)

        self.is_running = False
        return full_results, info

    def stop(self) -> None:
        self.is_running = False
