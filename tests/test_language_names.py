# -*- coding: utf-8 -*-
"""
Tests for language_names module.
"""
import pytest

from language_names import language_display_to_code, _kazakh_sort_key


class TestLanguageDisplayToCode:
    """Tests for language_display_to_code."""

    def test_auto_returns_none(self):
        assert language_display_to_code("Auto") is None
        assert language_display_to_code("  Auto  ") is None

    def test_empty_or_none_returns_none(self):
        assert language_display_to_code("") is None
        assert language_display_to_code(None) is None

    def test_whitespace_only_returns_empty_string(self):
        """Only whitespace is not 'Auto', so code returns stripped string (empty)."""
        assert language_display_to_code("   ") == ""

    def test_english_en_format_returns_code(self):
        assert language_display_to_code("English (en)") == "en"
        assert language_display_to_code("Russian (ru)") == "ru"

    def test_whitespace_around_parens(self):
        assert language_display_to_code(" English (en) ") == "en"

    def test_no_parens_returns_string_as_is(self):
        """Display value without parentheses is returned as-is (no code extracted)."""
        result = language_display_to_code("French")
        assert result == "French"

    def test_format_name_in_parens_returns_code(self):
        """Standard format 'Name (code)' extracts code: rsplit(' (', 1)[1][:-1] strips trailing ')'."""
        result = language_display_to_code("Something (en) (extra)")
        assert result == "extra"


class TestKazakhSortKey:
    """Tests for _kazakh_sort_key (internal but testable)."""

    def test_empty_string(self):
        assert _kazakh_sort_key("") == ()
        assert _kazakh_sort_key(None) == ()

    def test_kazakh_letters_ordered(self):
        # Order from _KAZAKH_ALPHABET: а=0, ә=1, б=2, ...
        key_a = _kazakh_sort_key("а")
        key_ae = _kazakh_sort_key("ә")
        key_b = _kazakh_sort_key("б")
        assert key_a < key_ae
        assert key_ae < key_b

    def test_unknown_chars_after_kazakh(self):
        # Unknown get 10000 + ord(c), so after any Kazakh letter
        key_latin = _kazakh_sort_key("a")
        key_kazakh = _kazakh_sort_key("а")
        assert key_kazakh < key_latin

    def test_lowercase_normalized(self):
        key_upper = _kazakh_sort_key("А")
        key_lower = _kazakh_sort_key("а")
        assert key_upper == key_lower
