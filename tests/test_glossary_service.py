# -*- coding: utf-8 -*-
"""
Tests for GlossaryService, GlossaryEntry, and GlossaryData.
"""
import json
import pytest

from GlossaryService import (
    GLOSSARY_SCHEMA_VERSION,
    GlossaryData,
    GlossaryEntry,
    GlossaryService,
)


class TestGlossaryEntry:
    """Tests for GlossaryEntry dataclass."""

    def test_from_dict_with_all_fields(self):
        data = {"original": "a", "corrected": "b", "created_at": "2024-01-01T00:00:00Z"}
        entry = GlossaryEntry.from_dict(data)
        assert entry.original == "a"
        assert entry.corrected == "b"
        assert entry.created_at == "2024-01-01T00:00:00Z"

    def test_from_dict_defaults_created_at(self):
        entry = GlossaryEntry.from_dict({"original": "x", "corrected": "y"})
        assert entry.original == "x"
        assert entry.corrected == "y"
        assert entry.created_at != ""
        assert "Z" in entry.created_at or "T" in entry.created_at

    def test_from_dict_ignores_unknown_keys(self):
        data = {"original": "a", "corrected": "b", "unknown_key": "ignored"}
        entry = GlossaryEntry.from_dict(data)
        assert entry.original == "a"
        assert entry.corrected == "b"

    def test_from_dict_defaults_empty_strings(self):
        entry = GlossaryEntry.from_dict({})
        assert entry.original == ""
        assert entry.corrected == ""

    def test_to_dict_roundtrip(self):
        entry = GlossaryEntry(original="test", corrected="Test")
        restored = GlossaryEntry.from_dict(entry.to_dict())
        assert restored.original == entry.original
        assert restored.corrected == entry.corrected
        assert restored.created_at == entry.created_at


class TestGlossaryData:
    """Tests for GlossaryData dataclass."""

    def test_from_dict_empty_entries(self):
        data = GlossaryData.from_dict({"version": 1})
        assert data.entries == []
        assert data.version == 1

    def test_from_dict_with_entries(self):
        raw = {
            "version": 1,
            "entries": [
                {"original": "a", "corrected": "A"},
                {"original": "b", "corrected": "B"},
            ],
        }
        data = GlossaryData.from_dict(raw)
        assert len(data.entries) == 2
        assert data.entries[0].original == "a"
        assert data.entries[1].corrected == "B"
        assert data.version == 1

    def test_from_dict_skips_non_dict_entries(self):
        raw = {"entries": [{"original": "a", "corrected": "A"}, "not-a-dict", None]}
        data = GlossaryData.from_dict(raw)
        assert len(data.entries) == 1
        assert data.entries[0].original == "a"

    def test_to_dict_roundtrip(self):
        entries = [
            GlossaryEntry(original="x", corrected="X"),
            GlossaryEntry(original="y", corrected="Y"),
        ]
        g = GlossaryData(entries=entries, version=GLOSSARY_SCHEMA_VERSION)
        restored = GlossaryData.from_dict(g.to_dict())
        assert len(restored.entries) == 2
        assert restored.entries[0].original == "x"
        assert restored.version == g.version


class TestGlossaryServiceLoadSave:
    """Tests for GlossaryService load/save with temp files."""

    def test_load_returns_data_from_valid_file(self, sample_glossary_json):
        data = GlossaryService.load(sample_glossary_json)
        assert data is not None
        assert len(data.entries) == 2
        assert data.entries[0].original == "вариант"
        assert data.entries[1].corrected == "Whisper"
        assert data.version == 1

    def test_load_returns_none_for_missing_file(self, tmp_path):
        result = GlossaryService.load(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_returns_none_for_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json {", encoding="utf-8")
        assert GlossaryService.load(str(path)) is None

    def test_save_creates_file_and_dir(self, tmp_path):
        out_path = tmp_path / "subdir" / "glossary.wiglossary"
        g = GlossaryData(entries=[GlossaryEntry(original="a", corrected="A")], version=1)
        success = GlossaryService.save(str(out_path), g)
        assert success is True
        assert out_path.exists()
        loaded = GlossaryService.load(str(out_path))
        assert loaded is not None
        assert len(loaded.entries) == 1
        assert loaded.entries[0].original == "a"

    def test_save_returns_false_on_permission_error(self, tmp_path):
        # Save to a path that is a directory (write will fail)
        g = GlossaryData(entries=[], version=1)
        success = GlossaryService.save(str(tmp_path), g)
        assert success is False


class TestGlossaryServiceAddRemove:
    """Tests for add_entry and remove_entry."""

    def test_add_entry_appends_new(self):
        g = GlossaryData(entries=[GlossaryEntry(original="a", corrected="A")], version=1)
        new_g = GlossaryService.add_entry(g, "b", "B")
        assert len(new_g.entries) == 2
        assert new_g.entries[1].original == "b"
        assert new_g.entries[1].corrected == "B"
        assert new_g.version == g.version

    def test_add_entry_updates_existing_by_original(self):
        g = GlossaryData(
            entries=[
                GlossaryEntry(original="a", corrected="A"),
                GlossaryEntry(original="b", corrected="B"),
            ],
            version=1,
        )
        new_g = GlossaryService.add_entry(g, "a", "A2")
        assert len(new_g.entries) == 2
        originals = [e.original for e in new_g.entries]
        assert "a" in originals
        corrected_a = next(e for e in new_g.entries if e.original == "a")
        assert corrected_a.corrected == "A2"

    def test_add_entry_ignores_empty_original(self):
        g = GlossaryData(entries=[GlossaryEntry(original="a", corrected="A")], version=1)
        new_g = GlossaryService.add_entry(g, "  ", "x")
        assert new_g is g
        assert len(new_g.entries) == 1

    def test_remove_entry_removes_by_original(self):
        g = GlossaryData(
            entries=[
                GlossaryEntry(original="a", corrected="A"),
                GlossaryEntry(original="b", corrected="B"),
            ],
            version=1,
        )
        new_g = GlossaryService.remove_entry(g, "a")
        assert len(new_g.entries) == 1
        assert new_g.entries[0].original == "b"

    def test_remove_entry_no_op_if_not_found(self):
        g = GlossaryData(entries=[GlossaryEntry(original="a", corrected="A")], version=1)
        new_g = GlossaryService.remove_entry(g, "z")
        assert len(new_g.entries) == 1
        assert new_g.entries[0].original == "a"


class TestGlossaryServiceInitialPrompt:
    """Tests for get_initial_prompt_text."""

    def test_empty_glossary_returns_empty_string(self):
        g = GlossaryData(entries=[], version=1)
        assert GlossaryService.get_initial_prompt_text(g) == ""

    def test_single_entry_format(self):
        g = GlossaryData(
            entries=[GlossaryEntry(original="whisper", corrected="Whisper")],
            version=1,
        )
        text = GlossaryService.get_initial_prompt_text(g)
        assert "Use these terms as written:" in text
        assert "whisper -> Whisper" in text

    def test_skips_entries_with_empty_original_or_corrected(self):
        g = GlossaryData(
            entries=[
                GlossaryEntry(original="a", corrected="A"),
                GlossaryEntry(original="", corrected="x"),
                GlossaryEntry(original="b", corrected=""),
            ],
            version=1,
        )
        text = GlossaryService.get_initial_prompt_text(g)
        assert "a -> A" in text
        assert "-> x" not in text
        assert "b ->" not in text
