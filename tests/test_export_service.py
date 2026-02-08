# -*- coding: utf-8 -*-
"""
Tests for ExportService.
"""
import pytest

from ExportService import ExportService


class TestExportServiceExportToTxt:
    """Tests for export_to_txt."""

    def test_export_to_txt_creates_file_with_segments(self, tmp_path, sample_transcript):
        output_path = tmp_path / "out.txt"
        success = ExportService.export_to_txt(sample_transcript, str(output_path))
        assert success is True
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "[0.0s - 2.5s]" in content
        assert "Hello world" in content
        assert "[2.5s - 5.0s]" in content
        assert "Second segment" in content

    def test_export_to_txt_empty_results(self, tmp_path):
        output_path = tmp_path / "empty.txt"
        success = ExportService.export_to_txt([], str(output_path))
        assert success is True
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == ""

    def test_export_to_txt_float_formatting(self, tmp_path):
        results = [{"start": 1.234, "end": 5.678, "text": "One"}]
        output_path = tmp_path / "fmt.txt"
        ExportService.export_to_txt(results, str(output_path))
        content = output_path.read_text(encoding="utf-8")
        assert "1.2" in content
        assert "5.7" in content

    def test_export_to_txt_returns_false_when_path_is_directory(self, tmp_path):
        """Passing a directory as output path should fail (cannot open as file)."""
        success = ExportService.export_to_txt(
            [{"start": 0, "end": 1, "text": "x"}],
            str(tmp_path),  # path is dir, not file
        )
        assert success is False
