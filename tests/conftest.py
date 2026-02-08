# -*- coding: utf-8 -*-
"""
Shared pytest fixtures for Whisper Transcriber tests.
"""
import json
import sys
from pathlib import Path

import pytest

# Ensure project root is on path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def sample_transcript():
    """Sample transcript segments for export/session tests."""
    return [
        {"start": 0.0, "end": 2.5, "text": "Hello world"},
        {"start": 2.5, "end": 5.0, "text": "Second segment"},
    ]


@pytest.fixture
def sample_glossary_json(tmp_path):
    """Path to a valid glossary JSON file."""
    path = tmp_path / "test.wiglossary"
    data = {
        "version": 1,
        "entries": [
            {"original": "вариант", "corrected": "вариант", "created_at": "2024-01-01T00:00:00Z"},
            {"original": "whisper", "corrected": "Whisper", "created_at": "2024-01-02T00:00:00Z"},
        ],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


@pytest.fixture
def sample_session_json_v1(tmp_path):
    """Path to a v1-style .wiproject file (single audio + transcript)."""
    project = tmp_path / "project.wiproject"
    audio_rel = "audio.wav"
    data = {
        "version": 1,
        "audio_path": audio_rel,
        "transcript": [
            {"start": 0.0, "end": 1.0, "text": "First"},
            {"start": 1.0, "end": 2.0, "text": "Second"},
        ],
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "model_used": "base",
    }
    project.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(project)


@pytest.fixture
def sample_session_json_v2(tmp_path):
    """Path to a v2-style .wiproject file (file_transcripts + current_file)."""
    project = tmp_path / "project.wiproject"
    data = {
        "version": 2,
        "audio_path": "audio/one.wav",
        "transcript": [{"start": 0.0, "end": 1.0, "text": "From one"}],
        "file_transcripts": {
            "audio/one.wav": [{"start": 0.0, "end": 1.0, "text": "From one"}],
            "audio/two.wav": [{"start": 0.0, "end": 1.0, "text": "From two"}],
        },
        "current_file": "audio/two.wav",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
        "model_used": "base",
    }
    project.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(project)
