import os
import sys
import threading
from faster_whisper import WhisperModel

class TranscriptionService:
    def __init__(self):
        self.model = None
        self.is_running = False
        self._setup_dlls()

    def _setup_dlls(self):
        """Setup CUDA DLL paths for correct operation on Windows."""
        # Пути при работе внутри скомпилированного EXE (PyInstaller)
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            bundled_cublas = os.path.join(base_path, 'nvidia', 'cublas', 'bin')
            bundled_cudnn = os.path.join(base_path, 'nvidia', 'cudnn', 'bin')
            for p in [bundled_cublas, bundled_cudnn]:
                if os.path.exists(p):
                    os.add_dll_directory(p)
            return

        # Стандартные пути из test.py (пользовательские)
        user_cublas = r'C:\Users\Timsar\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\nvidia\cublas\bin'
        user_cudnn = r'C:\Users\Timsar\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\site-packages\nvidia\cudnn\bin'
        
        # Попытка найти DLL внутри пакетов, если пути выше недоступны
        try:
            import nvidia.cublas
            import nvidia.cudnn
            pkg_cublas = os.path.join(nvidia.cublas.__path__[0], 'bin')
            pkg_cudnn = os.path.join(nvidia.cudnn.__path__[0], 'bin')
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
        """Единый каталог кэша моделей (тот же, что используется при load_model)."""
        if getattr(sys, "frozen", False):
            return os.path.join(os.path.dirname(sys.executable), "models")
        return os.path.join(os.getcwd(), "models")

    def load_model(self, model_size="large-v3", device="cuda", compute_type="float16"):
        """Загрузка модели Whisper."""
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
                download_root=models_dir
            )
            return True
        except Exception as e:
            print(f"Error loading model: {e}")
            if device == "cuda":
                print("Trying to switch to CPU...")
                try:
                    self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
                    return True
                except Exception as e2:
                    print(f"Error loading on CPU: {e2}")
            return False

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
    ):
        """
        Transcribe audio/video file.
        language: None = auto-detect, or "ru", "en", etc.
        task: "transcribe" or "translate".
        """
        if not self.model:
            raise Exception("Model not loaded!")

        self.is_running = True
        kwargs = dict(
            beam_size=beam_size,
            vad_filter=vad_filter,
            word_timestamps=word_timestamps,
            task=task,
        )
        if initial_prompt and initial_prompt.strip():
            kwargs["initial_prompt"] = initial_prompt.strip()
        if language and language != "auto" and language.strip():
            kwargs["language"] = language.strip()

        segments, info = self.model.transcribe(
            file_path,
            **kwargs
        )

        full_results = []
        duration = info.duration

        for segment in segments:
            if not self.is_running:
                break
            
            segment_data = {
                'start': segment.start,
                'end': segment.end,
                'text': segment.text
            }
            full_results.append(segment_data)
            
            if progress_callback:
                progress_callback(segment.end, duration, segment.text)

        self.is_running = False
        return full_results, info

    def stop(self):
        """Stop transcription process."""
        self.is_running = False
