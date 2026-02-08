# -*- coding: utf-8 -*-
"""
Tests for SessionService and SessionData.
"""
import json
import os
from pathlib import Path

import pytest

from SessionService import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_MULTI_FILE,
    SessionData,
    SessionService,
)


class TestSessionData:
    """Tests for SessionData dataclass."""

    def test_from_dict_minimal(self):
        data = SessionData.from_dict({})
        assert data.audio_path == ""
        assert data.transcript == []
        assert data.created_at != ""
        assert data.updated_at != ""

    def test_from_dict_with_known_fields(self):
        raw = {
            "audio_path": "/path/audio.wav",
            "transcript": [{"start": 0, "end": 1, "text": "Hi"}],
            "model_used": "base",
            "version": 1,
        }
        data = SessionData.from_dict(raw)
        assert data.audio_path == "/path/audio.wav"
        assert len(data.transcript) == 1
        assert data.transcript[0]["text"] == "Hi"
        assert data.model_used == "base"
        assert data.version == 1

    def test_to_dict_omits_none_optional_fields(self):
        data = SessionData(
            audio_path="",
            transcript=[],
            version=SCHEMA_VERSION,
            file_transcripts=None,
            current_file_rel=None,
            enabled_dictionary_ids=None,
        )
        d = data.to_dict()
        assert "file_transcripts" not in d or d.get("file_transcripts") is None
        assert "current_file_rel" not in d or d.get("current_file_rel") is None


class TestSessionServicePaths:
    """Tests for path helpers _make_path_relative_to_project and _resolve_audio_path."""

    def test_make_path_relative_same_directory(self, tmp_path):
        project = tmp_path / "project" / "file.wiproject"
        project.parent.mkdir(parents=True, exist_ok=True)
        audio = tmp_path / "project" / "audio.wav"
        rel = SessionService._make_path_relative_to_project(str(audio), str(project))
        assert rel == "audio.wav" or rel.replace("\\", "/") == "audio.wav"

    def test_make_path_relative_subdir(self, tmp_path):
        project = tmp_path / "project" / "file.wiproject"
        project.parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "project" / "media").mkdir(exist_ok=True)
        audio = tmp_path / "project" / "media" / "audio.wav"
        rel = SessionService._make_path_relative_to_project(str(audio), str(project))
        assert "media" in rel
        assert "audio.wav" in rel

    def test_resolve_audio_path_relative(self, tmp_path):
        project = tmp_path / "project.wiproject"
        project.write_text("{}", encoding="utf-8")
        resolved = SessionService._resolve_audio_path("media/audio.wav", str(project))
        expected = os.path.normpath(os.path.join(tmp_path, "media", "audio.wav"))
        assert resolved == expected

    def test_resolve_audio_path_absolute_existing(self, tmp_path):
        existing = tmp_path / "existing.wav"
        existing.write_bytes(b"x")
        resolved = SessionService._resolve_audio_path(str(existing), str(tmp_path / "p.wiproject"))
        assert resolved == str(existing)


class TestSessionServiceSaveLoad:
    """Tests for save_session and load_session."""

    def test_save_and_load_roundtrip_v2(self, tmp_path, sample_transcript):
        project_path = str(tmp_path / "test.wiproject")
        session = SessionData(
            audio_path=str(tmp_path / "audio.wav"),
            transcript=sample_transcript,
            model_used="base",
            version=SCHEMA_VERSION,
            file_transcripts={"audio.wav": sample_transcript},
            current_file_rel="audio.wav",
        )
        success = SessionService.save_session(project_path, session)
        assert success is True
        loaded = SessionService.load_session(project_path)
        assert loaded is not None
        assert len(loaded.transcript) == 2
        assert loaded.transcript[0]["text"] == "Hello world"
        assert loaded.current_file_rel == "audio.wav"
        assert loaded.audio_path == os.path.normpath(os.path.join(tmp_path, "audio.wav"))

    def test_save_v1_style_then_load(self, tmp_path, sample_transcript):
        project_path = str(tmp_path / "test.wiproject")
        session = SessionData(
            audio_path=str(tmp_path / "only.wav"),
            transcript=sample_transcript,
            model_used="base",
            version=SCHEMA_VERSION,
            file_transcripts=None,
            current_file_rel=None,
        )
        success = SessionService.save_session(project_path, session)
        assert success is True
        loaded = SessionService.load_session(project_path)
        assert loaded is not None
        assert loaded.file_transcripts is not None
        assert "only.wav" in loaded.file_transcripts or any("only" in k for k in loaded.file_transcripts)
        assert len(loaded.transcript) == 2

    def test_load_v1_file_fills_file_transcripts(self, sample_session_json_v1):
        session = SessionService.load_session(sample_session_json_v1)
        assert session is not None
        assert session.file_transcripts is not None
        assert "audio.wav" in session.file_transcripts
        assert len(session.transcript) == 2
        assert session.current_file_rel == "audio.wav"

    def test_load_v2_file_uses_current_file(self, sample_session_json_v2, tmp_path):
        # sample_session_json_v2 has current_file = "audio/two.wav"
        session = SessionService.load_session(sample_session_json_v2)
        assert session is not None
        assert session.current_file_rel == "audio/two.wav"
        assert session.transcript[0]["text"] == "From two"

    def test_load_session_returns_none_for_missing_file(self, tmp_path):
        result = SessionService.load_session(str(tmp_path / "missing.wiproject"))
        assert result is None

    def test_load_session_returns_none_for_invalid_json(self, tmp_path):
        path = tmp_path / "bad.wiproject"
        path.write_text("not json", encoding="utf-8")
        assert SessionService.load_session(str(path)) is None


class TestSessionServiceBuildSession:
    """Tests for build_session factory."""

    def test_build_session_basic(self, sample_transcript):
        s = SessionService.build_session(
            audio_path="/path/audio.wav",
            transcript=sample_transcript,
            model_used="large",
        )
        assert s.audio_path == "/path/audio.wav"
        assert len(s.transcript) == 2
        assert s.model_used == "large"
        assert s.file_transcripts is None
        assert s.current_file_rel is None

    def test_build_session_v2_with_file_transcripts(self, tmp_path, sample_transcript):
        project_path = str(tmp_path / "p.wiproject")
        file_transcripts = {"a.wav": sample_transcript, "b.wav": []}
        s = SessionService.build_session(
            audio_path=str(tmp_path / "a.wav"),
            transcript=sample_transcript,
            project_path=project_path,
            file_transcripts=file_transcripts,
            current_file_rel="a.wav",
        )
        assert s.file_transcripts == file_transcripts
        assert s.current_file_rel == "a.wav"

    def test_build_session_v2_current_file_inferred_from_audio_path(self, tmp_path, sample_transcript):
        project_path = str(tmp_path / "proj" / "p.wiproject")
        (tmp_path / "proj").mkdir(exist_ok=True)
        audio = str(tmp_path / "proj" / "audio.wav")
        s = SessionService.build_session(
            audio_path=audio,
            transcript=sample_transcript,
            project_path=project_path,
            file_transcripts={"audio.wav": sample_transcript},
            current_file_rel=None,
        )
        assert s.current_file_rel is not None
        assert "audio" in s.current_file_rel
