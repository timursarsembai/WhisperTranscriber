# -*- coding: utf-8 -*-
"""
Record audio from the default microphone to a WAV file.
Uses sounddevice for capture and soundfile for writing.
Supports device selection and software gain.
"""

import os
import tempfile
import threading
import time
from datetime import datetime
from typing import List, Optional, Tuple

try:
    import numpy as np
    import sounddevice as sd
    import soundfile as sf
    MIC_AVAILABLE = True
except ImportError:
    MIC_AVAILABLE = False


class MicRecordService:
    """Record from microphone to a WAV file. Start, then stop_and_save to get the file path."""

    def __init__(self, sample_rate: int = 44100, channels: int = 1):
        self.sample_rate = sample_rate
        self.channels = channels
        self._recording = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._chunks: list = []
        self._chunks_lock = threading.Lock()
        self._stream: Optional["sd.InputStream"] = None
        self._gain = 1.0  # software gain (multiplier for samples)

    @staticmethod
    def is_available() -> bool:
        """Return True if sounddevice and soundfile are installed and usable."""
        return MIC_AVAILABLE

    @staticmethod
    def get_input_devices() -> List[Tuple[int, str]]:
        """Return list of (device_index, device_name) for input devices, without duplicate names (Windows reports same device multiple times)."""
        if not MIC_AVAILABLE:
            return []
        try:
            devices = sd.query_devices()
            out = []
            seen_names = set()
            for i, dev in enumerate(devices):
                if dev.get("max_input_channels", 0) > 0:
                    name = (dev.get("name") or "Device %s" % i).strip()
                    if name and name not in seen_names:
                        seen_names.add(name)
                        out.append((i, name))
            return out
        except Exception:
            return []

    def set_gain(self, gain: float) -> None:
        """Set software gain (e.g. 0.5 = half, 2.0 = double). Applied when recording."""
        self._gain = max(0.1, min(5.0, float(gain)))

    def is_recording(self) -> bool:
        """Return True if recording is in progress."""
        return self._recording

    def start_recording(self, device: Optional[int] = None) -> Optional[str]:
        """
        Start recording in a background thread.
        device: sounddevice input device index, or None for default.
        Returns None on success, or an error message on failure.
        """
        if not MIC_AVAILABLE:
            return "sounddevice and soundfile are required. Install with: pip install sounddevice soundfile"
        if self._recording:
            return "Already recording"
        self._stop_event.clear()
        self._chunks = []
        self._recording = True
        gain = self._gain

        def record_loop():
            try:
                block_ms = 200
                block_size = int(self.sample_rate * block_ms / 1000) * self.channels
                kwargs = dict(
                    samplerate=self.sample_rate,
                    channels=self.channels,
                    dtype="float32",
                    blocksize=block_size,
                )
                if device is not None:
                    kwargs["device"] = device
                with sd.InputStream(**kwargs) as stream:
                    while self._recording and not self._stop_event.is_set():
                        chunk, _ = stream.read(block_size)
                        if chunk is not None and len(chunk) > 0:
                            if gain != 1.0:
                                chunk = (chunk * gain).astype("float32")
                            with self._chunks_lock:
                                self._chunks.append(chunk.copy())
                        time.sleep(0.01)
            except Exception:
                pass
            self._recording = False

        self._thread = threading.Thread(target=record_loop, daemon=True)
        self._thread.start()
        return None

    def take_accumulated_chunks(self) -> Optional["np.ndarray"]:
        """
        Take and clear currently accumulated chunks (for streaming mode).
        Returns concatenated float32 array, or None if no data. Thread-safe with recording.
        """
        if not MIC_AVAILABLE:
            return None
        with self._chunks_lock:
            if not self._chunks:
                return None
            data = np.concatenate(self._chunks, axis=0)
            self._chunks = []
        return data

    def get_waveform_tail(self, max_samples: int = 600) -> Optional["np.ndarray"]:
        """
        Return a copy of the most recent samples for waveform display (does not consume chunks).
        Returns float32 array of shape (n,) or None. Thread-safe.
        """
        if not MIC_AVAILABLE:
            return None
        with self._chunks_lock:
            if not self._chunks:
                return None
            data = np.concatenate(self._chunks, axis=0)
        data = np.asarray(data).ravel()
        if len(data) > max_samples:
            data = data[-max_samples:].copy()
        return data

    def stop_and_save(self, output_dir: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Stop recording and save to a WAV file in output_dir (or temp dir if None).
        Returns (file_path, None) on success, (None, error_message) on failure.
        """
        if not self._recording and not self._chunks:
            return None, "No recording in progress or no data recorded"
        self._recording = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        if output_dir is None:
            output_dir = tempfile.gettempdir()
        os.makedirs(output_dir, exist_ok=True)
        with self._chunks_lock:
            chunks_snapshot = list(self._chunks)
            self._chunks = []
        if not chunks_snapshot:
            return None, "No audio data recorded"
        try:
            data = np.concatenate(chunks_snapshot, axis=0)
            # Имя файла: число.месяц.год_час.минута.секунда.wav
            now = datetime.now()
            base_name = now.strftime("%d.%m.%Y_%H.%M.%S")
            base = os.path.join(output_dir, base_name)
            path = base + ".wav"
            idx = 0
            while os.path.exists(path):
                idx += 1
                path = f"{base}_{idx}.wav"
            sf.write(path, data, self.sample_rate)
            return os.path.abspath(path), None
        except Exception as e:
            return None, str(e) or "Failed to save recording"
