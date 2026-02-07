# -*- coding: utf-8 -*-
# Names for faster-whisper language codes (from tokenizer._LANGUAGE_CODES).
# Used for "English (en)", "Russian (ru)" etc. in Settings.

try:
    from faster_whisper.tokenizer import _LANGUAGE_CODES as _LANG_CODES
except ImportError:
    _LANG_CODES = ()

# Порядок букв казахского алфавита (кириллица) для сортировки при locale kk
_KAZAKH_ALPHABET = (
    "аәбвгғдеёжзийкқлмнңоөпрстуұүфхһцчшщыіэюя"
)
_KAZAKH_ORDER = {c: i for i, c in enumerate(_KAZAKH_ALPHABET)}


def _kazakh_sort_key(s):
    """Ключ сортировки по казахскому алфавиту. Неизвестные символы идут после."""
    s = (s or "").lower()
    return tuple(_KAZAKH_ORDER.get(c, 10000 + ord(c)) for c in s)


# Code -> display name (alphabetical by name for sorting)
_LANG_NAMES = {
    "af": "Afrikaans", "am": "Amharic", "ar": "Arabic", "as": "Assamese",
    "az": "Azerbaijani", "ba": "Bashkir", "be": "Belarusian", "bg": "Bulgarian",
    "bn": "Bengali", "bo": "Tibetan", "br": "Breton", "bs": "Bosnian",
    "ca": "Catalan", "cs": "Czech", "cy": "Welsh", "da": "Danish",
    "de": "German", "el": "Greek", "en": "English", "es": "Spanish",
    "et": "Estonian", "eu": "Basque", "fa": "Persian", "fi": "Finnish",
    "fo": "Faroese", "fr": "French", "gl": "Galician", "gu": "Gujarati",
    "ha": "Hausa", "haw": "Hawaiian", "he": "Hebrew", "hi": "Hindi",
    "hr": "Croatian", "ht": "Haitian Creole", "hu": "Hungarian", "hy": "Armenian",
    "id": "Indonesian", "is": "Icelandic", "it": "Italian", "ja": "Japanese",
    "jw": "Javanese", "ka": "Georgian", "kk": "Kazakh", "km": "Khmer",
    "kn": "Kannada", "ko": "Korean", "la": "Latin", "lb": "Luxembourgish",
    "ln": "Lingala", "lo": "Lao", "lt": "Lithuanian", "lv": "Latvian",
    "mg": "Malagasy", "mi": "Maori", "mk": "Macedonian", "ml": "Malayalam",
    "mn": "Mongolian", "mr": "Marathi", "ms": "Malay", "mt": "Maltese",
    "my": "Burmese", "ne": "Nepali", "nl": "Dutch", "nn": "Norwegian Nynorsk",
    "no": "Norwegian", "oc": "Occitan", "pa": "Punjabi", "pl": "Polish",
    "ps": "Pashto", "pt": "Portuguese", "ro": "Romanian", "ru": "Russian",
    "sa": "Sanskrit", "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak",
    "sl": "Slovenian", "sn": "Shona", "so": "Somali", "sq": "Albanian",
    "sr": "Serbian", "su": "Sundanese", "sv": "Swedish", "sw": "Swahili",
    "ta": "Tamil", "te": "Telugu", "tg": "Tajik", "th": "Thai",
    "tk": "Turkmen", "tl": "Tagalog", "tr": "Turkish", "tt": "Tatar",
    "uk": "Ukrainian", "ur": "Urdu", "uz": "Uzbek", "vi": "Vietnamese",
    "yi": "Yiddish", "yo": "Yoruba", "zh": "Chinese", "yue": "Cantonese",
}


def get_language_combo_values():
    """Returns ['Auto', 'Afrikaans (af)', ...] with names translated and sorted by current locale."""
    try:
        from i18n import t, get_locale
    except ImportError:
        get_locale = lambda: "en"
        t = lambda k: _LANG_NAMES.get(k.replace("lang_name.", ""), k)
    if not _LANG_CODES:
        return ["Auto", "English (en)", "Russian (ru)"]
    items = []
    for code in _LANG_CODES:
        key = "lang_name." + code
        name = t(key)
        if name == key:
            name = _LANG_NAMES.get(code, code.capitalize())
        items.append((name, code))
    if get_locale() == "kk":
        items.sort(key=lambda x: (_kazakh_sort_key(x[0]), x[1]))
    else:
        items.sort(key=lambda x: (x[0].lower(), x[1]))
    return ["Auto"] + [f"{name} ({code})" for name, code in items]


def language_display_to_code(display_value):
    """'Auto' or 'English (en)' -> None or 'en'."""
    if not display_value or display_value.strip() == "Auto":
        return None
    s = display_value.strip()
    if s == "Auto":
        return None
    if " (" in s and s.endswith(")"):
        return s.rsplit(" (", 1)[1][:-1].strip()
    return s
