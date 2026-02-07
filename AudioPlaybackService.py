# -*- coding: utf-8 -*-
"""
Воспроизведение сегмента аудио (Play-at-line) для редактора транскрипта.
Использует pygame.mixer.music: поддержка MP3, WAV, OGG.
"""

import threading
from typing import Callable, Optional

try:
    import pygame
    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False


class AudioPlaybackService:
    """Воспроизведение отрезка аудиофайла по времени начала и конца (в секундах)."""

    def __init__(self, schedule_in_main_thread: Optional[Callable[[float, Callable[..., None]], None]] = None):
        """
        schedule_in_main_thread(delay_seconds, callback) — вызвать callback в главном потоке
        через delay_seconds (для остановки воспроизведения). Например: app.after(int(delay_seconds * 1000), callback).
        """
        self._schedule = schedule_in_main_thread
        self._lock = threading.Lock()
        self._initialized = False

    def _ensure_init(self) -> bool:
        if not PYGAME_AVAILABLE:
            return False
        with self._lock:
            if self._initialized:
                return True
            try:
                pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
                self._initialized = True
                return True
            except Exception:
                return False

    def is_available(self) -> bool:
        return PYGAME_AVAILABLE and self._ensure_init()

    def stop(self) -> None:
        """Остановить текущее воспроизведение."""
        if not PYGAME_AVAILABLE or not self._initialized:
            return
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    def play_segment(
        self,
        file_path: str,
        start_sec: float,
        end_sec: float,
    ) -> bool:
        """
        Воспроизвести фрагмент файла с start_sec по end_sec (в секундах).
        Запускает загрузку и старт в фоновом потоке; остановка по таймеру через schedule_in_main_thread.
        Возвращает True, если воспроизведение запущено.
        """
        if not self._ensure_init() or not self._schedule:
            return False
        duration = max(0.0, end_sec - start_sec)
        if duration <= 0:
            return False

        def _do_play():
            try:
                pygame.mixer.music.load(file_path)
                # pygame 2: play(loops=0, start=0.0, fade_ms=0)
                pygame.mixer.music.play(loops=0, start=start_sec, fade_ms=0)
            except Exception:
                return
            # Остановить через duration секунд (в главном потоке, т.к. stop может быть привязан к UI)
            delay_ms = int(duration * 1000)
            self._schedule(delay_ms, self.stop)

        threading.Thread(target=_do_play, daemon=True).start()
        return True
