# -*- coding: utf-8 -*-
"""
Tests for DictionaryService, DictionaryData, and DictionaryEntry.
"""
import json
import pytest

from DictionaryService import (
    DICTIONARY_SCHEMA_VERSION,
    TYPE_CORRECTION,
    TYPE_TERMS,
    DictionaryData,
    DictionaryEntry,
    DictionaryService,
)


class TestDictionaryEntry:
    """Tests for DictionaryEntry dataclass."""

    def test_from_dict_correction(self):
        entry = DictionaryEntry.from_dict({"original": "a", "corrected": "b"}, TYPE_CORRECTION)
        assert entry.original == "a"
        assert entry.corrected == "b"

    def test_from_dict_terms_uses_term(self):
        entry = DictionaryEntry.from_dict({"term": "Whisper"}, TYPE_TERMS)
        assert entry.term == "Whisper"
        assert entry.original == "Whisper"
        assert entry.corrected == "Whisper"

    def test_from_dict_terms_fallback_original_corrected(self):
        entry = DictionaryEntry.from_dict({"original": "x", "corrected": "x"}, TYPE_TERMS)
        assert entry.term == "x"

    def test_to_dict_correction(self):
        entry = DictionaryEntry(original="a", corrected="b")
        d = entry.to_dict(TYPE_CORRECTION)
        assert d == {"original": "a", "corrected": "b"}

    def test_to_dict_terms(self):
        entry = DictionaryEntry(term="X", original="X", corrected="X")
        d = entry.to_dict(TYPE_TERMS)
        assert d == {"term": "X"}


class TestDictionaryData:
    """Tests for DictionaryData from_dict/to_dict."""

    def test_from_dict_defaults_type_correction(self):
        data = DictionaryData.from_dict({"name": "Test"})
        assert data.type == TYPE_CORRECTION
        assert data.name == "Test"
        assert data.entries == []
        assert data.version == DICTIONARY_SCHEMA_VERSION

    def test_from_dict_terms_type(self):
        data = DictionaryData.from_dict({
            "type": "terms",
            "name": "T",
            "entries": [{"term": "A"}],
        })
        assert data.type == TYPE_TERMS
        assert len(data.entries) == 1
        assert data.entries[0].term == "A"

    def test_from_dict_invalid_type_falls_back_to_correction(self):
        data = DictionaryData.from_dict({"type": "unknown", "entries": []})
        assert data.type == TYPE_CORRECTION

    def test_to_dict_roundtrip(self):
        entries = [
            DictionaryEntry(original="a", corrected="A"),
            DictionaryEntry(original="b", corrected="B"),
        ]
        d = DictionaryData(type=TYPE_CORRECTION, name="MyDict", entries=entries, version=1)
        restored = DictionaryData.from_dict(d.to_dict())
        assert restored.type == d.type
        assert restored.name == d.name
        assert len(restored.entries) == 2
        assert restored.entries[0].original == "a"


class TestDictionaryServiceLoadSave:
    """Tests for load/save with temp files."""

    def test_load_valid_file(self, tmp_path):
        path = tmp_path / "dict.json"
        path.write_text(
            json.dumps({
                "version": 1,
                "type": "correction",
                "name": "Test",
                "entries": [{"original": "x", "corrected": "X"}],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        data = DictionaryService.load(str(path))
        assert data is not None
        assert data.name == "Test"
        assert len(data.entries) == 1
        assert data.entries[0].corrected == "X"

    def test_load_missing_returns_none(self, tmp_path):
        assert DictionaryService.load(str(tmp_path / "missing.json")) is None

    def test_save_creates_file(self, tmp_path):
        path = tmp_path / "out" / "d.widict"
        data = DictionaryData(
            type=TYPE_CORRECTION,
            name="N",
            entries=[DictionaryEntry(original="a", corrected="A")],
            version=1,
        )
        success = DictionaryService.save(str(path), data)
        assert success is True
        assert path.exists()
        loaded = DictionaryService.load(str(path))
        assert loaded is not None
        assert loaded.entries[0].original == "a"


class TestDictionaryServiceBuildInitialPrompt:
    """Tests for build_initial_prompt_text."""

    def test_empty_list_returns_empty_string(self):
        assert DictionaryService.build_initial_prompt_text([]) == ""

    def test_terms_only(self):
        d = DictionaryData(
            type=TYPE_TERMS,
            name="T",
            entries=[
                DictionaryEntry(term="Whisper"),
                DictionaryEntry(term="API"),
            ],
        )
        text = DictionaryService.build_initial_prompt_text([d])
        assert "Whisper" in text
        assert "API" in text
        assert "Use these terms as written:" in text

    def test_correction_only(self):
        d = DictionaryData(
            type=TYPE_CORRECTION,
            name="C",
            entries=[
                DictionaryEntry(original="вариант", corrected="вариант"),
                DictionaryEntry(original="api", corrected="API"),
            ],
        )
        text = DictionaryService.build_initial_prompt_text([d])
        assert "вариант -> вариант" in text
        assert "api -> API" in text

    def test_mixed_terms_and_correction(self):
        terms = DictionaryData(type=TYPE_TERMS, name="T", entries=[DictionaryEntry(term="X")])
        corr = DictionaryData(
            type=TYPE_CORRECTION,
            name="C",
            entries=[DictionaryEntry(original="a", corrected="A")],
        )
        text = DictionaryService.build_initial_prompt_text([terms, corr])
        assert "X" in text
        assert "a -> A" in text


class TestDictionaryServiceApplyCorrections:
    """Tests for apply_corrections_to_segments and get_correction_entries_from_dictionaries."""

    def test_apply_corrections_to_segments_in_place(self):
        segments = [
            {"start": 0.0, "end": 1.0, "text": "Hello whisper world"},
            {"start": 1.0, "end": 2.0, "text": "whisper again"},
        ]
        corrections = [
            {"original": "whisper", "corrected": "Whisper"},
        ]
        DictionaryService.apply_corrections_to_segments(segments, corrections)
        assert segments[0]["text"] == "Hello Whisper world"
        assert segments[1]["text"] == "Whisper again"

    def test_apply_corrections_empty_original_skipped(self):
        segments = [{"text": "Hello"}]
        DictionaryService.apply_corrections_to_segments(
            segments,
            [{"original": "", "corrected": "X"}],
        )
        assert segments[0]["text"] == "Hello"

    def test_get_correction_entries_from_dictionaries_ignores_terms(self):
        terms_dict = DictionaryData(
            type=TYPE_TERMS,
            name="T",
            entries=[DictionaryEntry(term="X")],
        )
        entries = DictionaryService.get_correction_entries_from_dictionaries([terms_dict])
        assert entries == []

    def test_get_correction_entries_from_dictionaries_returns_corrections(self):
        d = DictionaryData(
            type=TYPE_CORRECTION,
            name="C",
            entries=[
                DictionaryEntry(original="a", corrected="A"),
                DictionaryEntry(original="", corrected="x"),  # skipped
                DictionaryEntry(original="b", corrected="B"),
            ],
        )
        entries = DictionaryService.get_correction_entries_from_dictionaries([d])
        assert len(entries) == 2
        assert entries[0] == {"original": "a", "corrected": "A"}
        assert entries[1] == {"original": "b", "corrected": "B"}
