# -*- coding: utf-8 -*-
"""
ASR backends: abstraction and implementations.
Engine selection is done in TranscriptionService via transcription_engine config.
"""
from asr_backends.base import ASRBackend
from asr_backends.faster_whisper_backend import FasterWhisperBackend
from asr_backends.whisper_streaming_backend import WhisperStreamingBackend
from asr_backends.whisperx_backend import WhisperXBackend

__all__ = ["ASRBackend", "FasterWhisperBackend", "WhisperStreamingBackend", "WhisperXBackend"]
