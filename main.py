import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Dict, Optional
import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas, Frame, StringVar, Toplevel, Label, Menu
from TranscriptionService import TranscriptionService
import YouTubeDownloadService
from MicRecordService import MicRecordService


class DarkScrollbar(Canvas):
    """Кастомный скроллбар на Canvas: гарантированно видимый ползунок на любой ОС.

    Canvas сам рисует прямоугольники (трек + ползунок), поэтому не зависит
    от тем Windows, версии CustomTkinter и пр.

    Аргументы:
        parent     — родительский виджет
        width      — ширина скроллбара (px)
        command    — функция прокрутки (canvas.yview)
        track_color, thumb_color, thumb_hover_color — цвета
    """

    def __init__(self, parent, width=16, command=None,
                 track_color="#404040", thumb_color="#1F6AA5",
                 thumb_hover_color="#5DA1D4", **kw):
        super().__init__(parent, width=width, highlightthickness=0,
                         borderwidth=0, bg=track_color, **kw)
        self._cmd = command
        self._track_color = track_color
        self._thumb_color = thumb_color
        self._thumb_hover = thumb_hover_color
        self._first = 0.0
        self._last = 1.0
        self._thumb_id = self.create_rectangle(0, 0, 0, 0, fill=thumb_color, outline="")
        self._drag_y = None
        # Перерисовка при изменении размера / появлении на экране
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Map>", lambda e: self._draw())
        # Hover
        self.tag_bind(self._thumb_id, "<Enter>",
                      lambda e: self.itemconfig(self._thumb_id, fill=self._thumb_hover))
        self.tag_bind(self._thumb_id, "<Leave>",
                      lambda e: self.itemconfig(self._thumb_id, fill=self._thumb_color))
        # Drag
        self.tag_bind(self._thumb_id, "<Button-1>", self._press)
        self.tag_bind(self._thumb_id, "<B1-Motion>", self._drag)
        # Click on track
        self.bind("<Button-1>", self._track_click)

    # --- public API (вызывается Canvas‑ом) ---
    def set(self, first, last):
        """Canvas передаёт строки — обязательно конвертируем."""
        self._first = float(first)
        self._last = float(last)
        self._draw()

    # --- drawing ---
    def _draw(self):
        h = self.winfo_height()
        w = self.winfo_width()
        if h < 1 or self._last - self._first >= 1.0:
            self.coords(self._thumb_id, 0, 0, 0, 0)
            return
        y1 = int(self._first * h)
        y2 = int(self._last * h)
        min_thumb = min(20, h)    # минимальная высота ползунка, но не больше трека
        if y2 - y1 < min_thumb:
            y2 = y1 + min_thumb
        # не выходить за нижнюю границу трека — ползунок всегда целиком виден
        if y2 > h:
            y2 = h
            y1 = max(0, y2 - min_thumb)
        self.coords(self._thumb_id, 0, y1, w, y2)

    # --- interaction ---
    def _press(self, e):
        self._drag_y = e.y

    def _drag(self, e):
        if self._cmd is None or self._drag_y is None:
            return
        h = self.winfo_height()
        if h < 1:
            return
        dy = (e.y - self._drag_y) / h
        new = max(0.0, min(1.0 - (self._last - self._first),
                           self._first + dy))
        self._cmd("moveto", str(new))
        self._drag_y = e.y

    def _track_click(self, e):
        # Не реагировать, если клик по ползунку (tag_bind обработает)
        if self.find_withtag("current") == (self._thumb_id,):
            return
        if self._cmd is None:
            return
        h = self.winfo_height()
        if h < 1:
            return
        frac = e.y / h
        half = (self._last - self._first) / 2
        new = max(0.0, min(1.0 - (self._last - self._first), frac - half))
        self._cmd("moveto", str(new))


from ExportService import ExportService
from SessionService import SessionService
from GlossaryService import GlossaryService, GlossaryData
from OllamaService import OllamaService
from AudioPlaybackService import AudioPlaybackService
from language_names import get_language_combo_values, language_display_to_code
# UI strings: use t("key") for localized text; keys are in locales/en.json, locales/ru.json
from i18n import t, set_locale, get_locale, get_available_locales, load_locale_preference, save_locale_preference, load_config, save_config

# Маппинг размера модели из UI на repo_id в Hugging Face
MODEL_SIZE_TO_REPO = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
}

# Эмодзи флагов для выбора языка интерфейса (шрифт Segoe UI Emoji отображает их как флаги на Windows)
LANG_FLAGS = {"en": "\U0001f1ec\U0001f1e7", "es": "\U0001f1ea\U0001f1f8", "ru": "\U0001f1f7\U0001f1fa", "kk": "\U0001f1f0\U0001f1ff"}


def _format_size_bytes(size_bytes: int) -> str:
    """Форматирует размер в байтах в строку вида '450 MB' или '1.2 GB'."""
    if size_bytes < 0:
        return ""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024**3:.1f} GB"
    return f"{size_bytes / 1024**2:.0f} MB"


def _get_model_downloaded_size_bytes(cache_dir: str, model_id: str) -> Optional[int]:
    """Возвращает размер скачанной модели в байтах или None если не скачана."""
    folder = f"models--Systran--faster-whisper-{model_id}"
    snap_path = os.path.join(cache_dir, folder, "snapshots")
    if not os.path.isdir(snap_path):
        return None
    total = 0
    try:
        for root, _dirs, files in os.walk(snap_path):
            for f in files:
                path = os.path.join(root, f)
                try:
                    total += os.path.getsize(path)
                except (OSError, ValueError):
                    pass
    except (OSError, ValueError):
        return None
    return total if total > 0 else None


def _get_models_downloaded_status() -> Dict[str, bool]:
    """Возвращает словарь model_id -> True если модель скачана, иначе False."""
    cache_dir = TranscriptionService.get_models_cache_dir()
    result = {mid: False for mid in MODEL_SIZE_TO_REPO}
    try:
        import huggingface_hub as hfh
        if hasattr(hfh, "scan_cache_dir"):
            info = hfh.scan_cache_dir(cache_dir)
            for repo in getattr(info, "repos", []):
                repo_id = getattr(repo, "repo_id", None) or ""
                for mid, rid in MODEL_SIZE_TO_REPO.items():
                    if rid == repo_id:
                        result[mid] = True
                        break
            return result
    except Exception:
        pass
    # Запасной вариант: проверка папки и model.bin
    for mid in MODEL_SIZE_TO_REPO:
        folder = f"models--Systran--faster-whisper-{mid}"
        dir_path = os.path.join(cache_dir, folder, "snapshots")
        if not os.path.isdir(dir_path):
            continue
        bins = glob.glob(os.path.join(dir_path, "*", "model.bin"))
        if bins:
            result[mid] = True
    return result

# Splash screen support for PyInstaller
try:
    import pyi_splash
except ImportError:
    pyi_splash = None

# Настройка внешнего вида
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self, open_session_path: Optional[str] = None, project_dir: Optional[str] = None):
        super().__init__()

        self.title(t("app.title"))
        self.geometry("800x600")

        self.service = TranscriptionService()
        self.export_service = ExportService()
        self.ollama_service = OllamaService()
        self.audio_playback = AudioPlaybackService(
            schedule_in_main_thread=lambda ms, cb: self.after(int(ms), cb)
        )
        self.mic_record = MicRecordService()
        self.full_results = []
        self.current_file = None
        self.current_session_path = None  # путь к открытому/сохранённому .wiproject
        self.current_project_dir = None  # папка проекта (для нового проекта или папка с .wiproject)
        self._session_dirty = False  # были ли изменения после последнего сохранения
        self.current_glossary_path = None
        self.current_glossary = None  # GlossaryData or None
        self.file_transcripts = {}  # rel_path -> list of segments (multi-file project state)

        if project_dir and os.path.isdir(project_dir):
            self.current_project_dir = os.path.abspath(project_dir)
        if open_session_path and os.path.isfile(open_session_path):
            self.current_project_dir = os.path.dirname(os.path.abspath(open_session_path))

        self._setup_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if open_session_path:
            self._open_session_with_path(open_session_path)
        if self.current_project_dir and not self.current_session_path:
            self._update_session_title()

        # Close splash screen if it's running
        if pyi_splash:
            pyi_splash.close()

    def _setup_ui(self):
        self._tooltip_after_id = None
        self._tooltip_win = None
        self._left_panel_width = 220
        self._right_panel_width = 300
        # Три колонки: [Project files] [Content] [Settings]
        self.grid_columnconfigure(0, minsize=self._left_panel_width)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)
        self.grid_rowconfigure(3, weight=1)
        self.grid_rowconfigure(5, weight=0)

        # --- Левая панель: заголовок+кнопки отдельно, ниже — список файлов ---
        self._left_panel = ctk.CTkFrame(self, width=self._left_panel_width, fg_color=("gray90", "gray18"))
        self._left_panel.grid(row=0, column=0, rowspan=6, padx=(20, 0), pady=(0, 20), sticky="nsew")
        self._left_panel.grid_propagate(False)
        self._left_panel.grid_columnconfigure(0, weight=1)
        self._left_panel.grid_rowconfigure(2, weight=1)
        self._left_panel_header = ctk.CTkFrame(self._left_panel, fg_color=("gray85", "gray22"), corner_radius=6)
        self._left_panel_header.grid(row=0, column=0, padx=6, pady=(8, 0), sticky="ew")
        self._left_panel_header.grid_columnconfigure(0, weight=1)
        self._left_panel_title = ctk.CTkLabel(
            self._left_panel_header, text=t("project_files.title"), font=ctk.CTkFont(size=13, weight="bold")
        )
        self._left_panel_title.grid(row=0, column=0, padx=10, pady=(10, 8), sticky="w")
        self._left_panel_sep = ctk.CTkFrame(self._left_panel, fg_color=("gray75", "gray28"), height=1)
        self._left_panel_sep.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 4))
        self._left_panel_sep.grid_propagate(False)
        self._left_panel_files_scroll = ctk.CTkScrollableFrame(self._left_panel, fg_color="transparent")
        self._left_panel_files_scroll.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 8))
        self._left_panel_files_scroll.grid_columnconfigure(0, weight=1)
        self._bind_project_files_wheel()

        # --- Панель управления: Открыть, Сохранить, Выбрать файл, Микрофон, Импорт из YouTube ---
        _icon_font = ctk.CTkFont(size=20)
        self.top_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_frame.grid(row=0, column=1, padx=20, pady=(10, 6), sticky="ew")
        self.top_frame.grid_columnconfigure(5, weight=1)
        self.top_frame.grid_rowconfigure(1, weight=0)
        self.btn_open_session = ctk.CTkButton(
            self.top_frame, text=t("session.open_project"), width=100, height=32,
            command=self._open_session,
        )
        self.btn_open_session.grid(row=0, column=0, padx=(0, 4), pady=0)
        self.btn_save_session = ctk.CTkButton(
            self.top_frame, text=t("session.save_project"), width=100, height=32,
            command=self._save_session, state="disabled",
        )
        self.btn_save_session.grid(row=0, column=1, padx=(0, 4), pady=0)
        self.btn_browse = ctk.CTkButton(
            self.top_frame, text=t("top.browse_file"), width=100, height=32,
            command=self._browse_file,
        )
        self.btn_browse.grid(row=0, column=2, padx=(0, 4), pady=0)
        self.btn_mic_record = ctk.CTkButton(
            self.top_frame, text=t("top.mic"), width=100, height=32,
            command=self._show_mic_panel,
        )
        self.btn_mic_record.grid(row=0, column=3, padx=(0, 4), pady=0)
        self.btn_import_youtube = ctk.CTkButton(
            self.top_frame, text=t("top.import_youtube"), width=140, height=32,
            command=self._toggle_youtube_panel,
        )
        self.btn_import_youtube.grid(row=0, column=4, padx=(0, 10), pady=0)
        self._bind_tooltip(self.btn_open_session, "session.open_project")
        self._bind_tooltip(self.btn_save_session, "session.save_project")
        self._bind_tooltip(self.btn_browse, "top.browse_file")
        self._bind_tooltip(self.btn_mic_record, "import.mic_record_tooltip")
        self._bind_tooltip(self.btn_import_youtube, "import.load_youtube_tooltip")
        self._youtube_frame = ctk.CTkFrame(self.top_frame, fg_color="transparent")
        self._youtube_frame.grid(row=1, column=0, columnspan=6, sticky="ew", padx=0, pady=(8, 0))
        self._youtube_frame.grid_remove()  # скрыта по умолчанию, показывается по кнопке «Импорт из YouTube»
        self._youtube_panel_visible = False
        self._youtube_frame.grid_columnconfigure(1, weight=1)
        self._youtube_entry = ctk.CTkEntry(
            self._youtube_frame, placeholder_text=t("import.youtube_placeholder"), width=420,
        )
        self._youtube_entry.grid(row=0, column=0, padx=(0, 6), pady=4, sticky="ew")
        self._youtube_entry.bind("<Control-KeyPress>", self._youtube_entry_paste_by_keycode)
        self.btn_youtube_load = ctk.CTkButton(
            self._youtube_frame, text=t("import.load_youtube"), width=100,
            command=self._load_from_youtube,
        )
        self.btn_youtube_load.grid(row=0, column=1, padx=0, pady=4, sticky="w")
        self._bind_tooltip(self.btn_youtube_load, "import.load_youtube_tooltip")

        # Строка: [Старт] [Стоп] | прогресс-бар транскрибации
        self.control_frame = ctk.CTkFrame(self, fg_color=("gray92", "gray24"), corner_radius=6)
        self.control_frame.grid(row=1, column=1, padx=20, pady=(6, 6), sticky="ew")
        self.control_frame.grid_columnconfigure(2, weight=1)
        self.btn_start = ctk.CTkButton(
            self.control_frame, text=t("control.start"), width=120, height=28,
            command=self._start_transcription, fg_color="green", hover_color="darkgreen",
        )
        self.btn_start.grid(row=0, column=0, padx=(8, 4), pady=6)
        self.btn_stop = ctk.CTkButton(
            self.control_frame, text=t("control.stop"), width=80, height=28,
            command=self._stop_transcription, state="disabled", fg_color="red", hover_color="darkred",
        )
        self.btn_stop.grid(row=0, column=1, padx=(0, 8), pady=6)
        self.progress_bar = ctk.CTkProgressBar(self.control_frame, height=12)
        self.progress_bar.grid(row=0, column=2, padx=(0, 8), pady=6, sticky="ew")
        self.progress_bar.set(0)
        self._bind_tooltip(self.btn_start, "control.start")
        self._bind_tooltip(self.btn_stop, "control.stop")

        # Под прогресс-баром — подпись с именем файла (или «Файл не выбран (форматы)»)
        self._file_status_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._file_status_frame.grid(row=2, column=1, padx=20, pady=(0, 8), sticky="ew")
        self._file_status_frame.grid_columnconfigure(0, weight=1)
        self.lbl_file = ctk.CTkLabel(self._file_status_frame, text=t("top.no_file_formats"), anchor="w")
        self.lbl_file.grid(row=0, column=0, padx=10, sticky="w")

        # Область вывода: во время транскрипции — потоковый текст; после — список сегментов с Play-at-line
        self._editor_container = ctk.CTkFrame(self, fg_color="transparent")
        self._editor_container.grid(row=3, column=1, padx=20, pady=(0, 20), sticky="nsew")
        self._editor_container.grid_columnconfigure(0, weight=1)
        self._editor_container.grid_rowconfigure(0, weight=1)
        self.txt_output = ctk.CTkTextbox(self._editor_container, font=("Segoe UI", 12))
        self.txt_output.grid(row=0, column=0, sticky="nsew")
        self._segment_scroll = ctk.CTkScrollableFrame(self._editor_container, fg_color="transparent")
        self._segment_scroll.grid(row=0, column=0, sticky="nsew")
        self._segment_scroll.grid_columnconfigure(0, weight=1)
        self._segment_scroll.grid_remove()  # по умолчанию показываем txt_output (пустой)

        # Единая панель записи с микрофона: переключатель режима, глоссарий (по режиму), Старт/Стоп, таймер, осциллограф
        self._recording_panel_container = ctk.CTkFrame(self, fg_color=("gray92", "gray22"), corner_radius=6)
        self._recording_panel_container.grid(row=4, column=1, padx=20, pady=(0, 8), sticky="w")
        self._recording_panel_container.grid_remove()
        self._recording_panel_container.grid_columnconfigure(0, weight=0)
        self._mic_panel_nominal_width = 720
        _mic_panel_header = ctk.CTkFrame(self._recording_panel_container, fg_color="transparent")
        _mic_panel_header.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))
        _mic_panel_header.grid_columnconfigure(0, weight=1)
        self._btn_mic_panel_close = ctk.CTkButton(
            _mic_panel_header, text="\u00D7", width=28, height=28, font=ctk.CTkFont(size=18),
            command=self._hide_mic_panel, fg_color="transparent", hover_color=("gray75", "gray35"),
        )
        self._btn_mic_panel_close.grid(row=0, column=1, padx=0, pady=0)
        self._bind_tooltip(self._btn_mic_panel_close, "mic.close_panel")
        self._mic_unified_panel = ctk.CTkFrame(self._recording_panel_container, fg_color="transparent")
        self._mic_unified_panel.grid(row=1, column=0, sticky="nw", padx=12, pady=(0, 10))
        self._mic_unified_panel.grid_columnconfigure(0, weight=0)
        self._mic_unified_panel.grid_columnconfigure(1, weight=0)
        self._mic_current_mode = "normal"
        self._mic_normal_use_glossary_var = ctk.BooleanVar(value=False)
        self._mic_streaming_use_glossary_var = ctk.BooleanVar(value=False)
        self._mic_glossary_ui_var = ctk.BooleanVar(value=False)
        self._mic_mode_var = StringVar(value=t("mic.mode_normal"))
        # Левая колонка: микрофон — режим, глоссарий, статус, Старт/Стоп, таймер, осциллограф
        self._mic_left_col = ctk.CTkFrame(self._mic_unified_panel, fg_color="transparent")
        self._mic_left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        self._mic_left_col.grid_columnconfigure(0, weight=1)
        self._mic_mode_buttons = ctk.CTkSegmentedButton(
            self._mic_left_col,
            values=[t("mic.mode_normal"), t("mic.mode_streaming")],
            variable=self._mic_mode_var,
            command=self._on_mic_mode_changed,
        )
        self._mic_mode_buttons.grid(row=0, column=0, sticky="w", pady=(0, 4))
        self._mic_glossary_cb = ctk.CTkCheckBox(self._mic_left_col, text=t("mic.use_glossary"), variable=self._mic_glossary_ui_var)
        self._mic_glossary_cb.grid(row=1, column=0, sticky="w", pady=2)
        self._mic_status = ctk.CTkLabel(self._mic_left_col, text="", font=ctk.CTkFont(size=12))
        self._mic_status.grid(row=2, column=0, sticky="w", pady=(0, 2))
        self._mic_waveform_f = ctk.CTkFrame(self._mic_left_col, fg_color=("gray85", "gray28"), height=48)
        self._mic_waveform_f.grid(row=3, column=0, pady=(0, 8), sticky="ew")
        self._mic_waveform_f.grid_propagate(False)
        self._waveform_canvas_mic = Canvas(
            self._mic_waveform_f, width=360, height=48,
            bg="#3d3d3d", highlightthickness=0,
        )
        self._waveform_canvas_mic.pack(fill="both", expand=True)
        _mic_btn_row = ctk.CTkFrame(self._mic_left_col, fg_color="transparent")
        _mic_btn_row.grid(row=4, column=0, padx=(0, 8), pady=0, sticky="w")
        self._mic_start_btn = ctk.CTkButton(_mic_btn_row, text=t("import.mic_start"), width=100, command=self._on_mic_start)
        self._mic_start_btn.pack(side="left", padx=(0, 4))
        self._mic_stop_btn = ctk.CTkButton(_mic_btn_row, text=t("import.mic_stop"), width=100, state="disabled", fg_color="red", hover_color="darkred", command=self._on_mic_stop)
        self._mic_stop_btn.pack(side="left")
        self._mic_timer = ctk.CTkLabel(_mic_btn_row, text="00:00", font=ctk.CTkFont(size=22))
        self._mic_timer.pack(side="left", padx=(12, 0))
        # Правая колонка: настройки микрофона — устройство, два микшера (колонка 1 = название, колонка 2 = ползунок + %)
        self._mic_right_col = ctk.CTkFrame(self._mic_unified_panel, fg_color="transparent")
        self._mic_right_col.grid(row=0, column=1, sticky="nw", padx=0)
        self._mic_right_col.grid_columnconfigure(0, minsize=220)
        self._mic_right_col.grid_columnconfigure(1, weight=1)
        self._mic_device_var = StringVar(value=t("mic.input_device_default"))
        _devices = MicRecordService.get_input_devices()
        self._mic_device_list = _devices
        _device_names = [t("mic.input_device_default")] + [name for _, name in _devices]
        self._mic_device_option = ctk.CTkOptionMenu(
            self._mic_right_col, variable=self._mic_device_var, values=_device_names,
            width=220, command=self._on_mic_device_changed,
        )
        self._mic_device_option.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self._mic_software_gain = ctk.DoubleVar(value=1.0)
        self._mic_gain_software_title = ctk.CTkLabel(self._mic_right_col, text=t("mic.gain_software"), font=ctk.CTkFont(size=12))
        self._mic_gain_software_title.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=2)
        _mic_sw_col = ctk.CTkFrame(self._mic_right_col, fg_color="transparent")
        _mic_sw_col.grid(row=1, column=1, sticky="ew", padx=0, pady=2)
        _mic_sw_col.grid_columnconfigure(0, weight=1)
        self._mic_software_slider = ctk.CTkSlider(_mic_sw_col, from_=0.25, to=2.0, variable=self._mic_software_gain, width=160, command=self._on_mic_software_gain_changed)
        self._mic_software_slider.grid(row=0, column=0, sticky="w", padx=0)
        self._mic_software_label = ctk.CTkLabel(_mic_sw_col, text="100%", font=ctk.CTkFont(size=11))
        self._mic_software_label.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self._mic_system_volume_available = False
        try:
            if sys.platform == "win32":
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # noqa: F401
                from comtypes import CLSCTX_ALL  # noqa: F401
                self._mic_system_volume_available = True
        except Exception:
            pass
        self._mic_system_volume = ctk.DoubleVar(value=1.0)
        self._mic_gain_system_title = ctk.CTkLabel(self._mic_right_col, text=t("mic.gain_system"), font=ctk.CTkFont(size=12))
        self._mic_gain_system_title.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=2)
        _mic_sys_col = ctk.CTkFrame(self._mic_right_col, fg_color="transparent")
        _mic_sys_col.grid(row=2, column=1, sticky="ew", padx=0, pady=2)
        _mic_sys_col.grid_columnconfigure(0, weight=1)
        self._mic_system_slider = ctk.CTkSlider(_mic_sys_col, from_=0.0, to=1.0, variable=self._mic_system_volume, width=160, command=self._on_mic_system_volume_changed)
        self._mic_system_slider.grid(row=0, column=0, sticky="w", padx=0)
        self._mic_system_pct_label = ctk.CTkLabel(_mic_sys_col, text="100%", font=ctk.CTkFont(size=11))
        self._mic_system_pct_label.grid(row=0, column=1, sticky="w", padx=(6, 0))
        if not self._mic_system_volume_available:
            self._mic_gain_system_title.configure(text=t("mic.gain_system_unavailable"))
            self._mic_system_slider.configure(state="disabled")
        self._mic_normal_timer_job = None
        self._mic_normal_elapsed = [0.0]
        self._mic_streaming_timer_job = [None]
        self._mic_streaming_elapsed = [0.0]
        self._mic_panel_visible = False

        # Правая панель: своя разметка — кнопки вкладок вверху, контент сразу под ними (без CTkTabview). По умолчанию видна.
        self.settings_panel_visible = True
        self._right_panel = ctk.CTkFrame(self, width=self._right_panel_width, fg_color=("gray85", "gray20"))
        self._right_panel.grid(row=0, column=2, rowspan=6, padx=(0, 20), pady=(0, 20), sticky="nsew")
        self.grid_columnconfigure(2, minsize=self._right_panel_width)
        self._right_panel.grid_propagate(False)
        self._right_panel.grid_columnconfigure(0, weight=1)
        self._right_panel.grid_rowconfigure(1, weight=1)  # контент в row 1 растягивается
        self.geometry(f"{800 + self._left_panel_width + self._right_panel_width}x600")
        self.after(100, self._force_update_scroll_regions)
        self.after(50, self._maximize_window)
        self.bind("<Configure>", lambda e: self._update_mic_panel_width(e))
        # Строка вкладок — сразу вверху, без отступа
        self._settings_tab_index = 0  # 0=Transcription, 1=Glossary, 2=Interface
        self._settings_tab_var = StringVar(value=t("tabs.transcription"))
        self._settings_tab_buttons = ctk.CTkSegmentedButton(
            self._right_panel,
            values=[t("tabs.transcription"), t("tabs.glossary"), t("tabs.interface")],
            variable=self._settings_tab_var,
            command=self._on_settings_tab_changed,
        )
        self._settings_tab_buttons.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 6))
        # Контейнер контента вкладок
        self._settings_tab_content = ctk.CTkFrame(self._right_panel, fg_color="transparent")
        self._settings_tab_content.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self._settings_tab_content.grid_columnconfigure(0, weight=1)
        self._settings_tab_content.grid_rowconfigure(0, weight=1)
        # Три фрейма контента в одной ячейке, переключаем grid/grid_remove
        self._tab_transcription = ctk.CTkFrame(self._settings_tab_content, fg_color="transparent")
        self._tab_transcription.grid(row=0, column=0, sticky="nsew")
        self._tab_transcription.grid_columnconfigure(0, weight=1)
        self._tab_transcription.grid_rowconfigure(0, weight=1)
        self._tab_glossary = ctk.CTkFrame(self._settings_tab_content, fg_color="transparent")
        self._tab_glossary.grid(row=0, column=0, sticky="nsew")
        self._tab_glossary.grid_remove()
        self._tab_glossary.grid_columnconfigure(0, weight=1)
        self._tab_glossary.grid_rowconfigure(1, weight=1)
        self._tab_interface = ctk.CTkFrame(self._settings_tab_content, fg_color="transparent")
        self._tab_interface.grid(row=0, column=0, sticky="nsew")
        self._tab_interface.grid_remove()
        self._tab_interface.grid_columnconfigure(0, weight=1)
        self._tab_interface.grid_rowconfigure(0, weight=1)
        self._build_settings_panel(self._tab_transcription)
        self._build_glossary_panel(self._tab_glossary)
        self._build_interface_settings_panel(self._tab_interface)

        # Bottom panel: Export, Ollama, справа — Настройки
        self.export_frame = ctk.CTkFrame(self)
        self.export_frame.grid(row=5, column=1, padx=20, pady=(0, 20), sticky="ew")
        self.export_frame.grid_columnconfigure(2, weight=1)
        self.btn_export_txt = ctk.CTkButton(self.export_frame, text=t("export.txt"), command=self._export_txt, state="disabled")
        self.btn_export_txt.grid(row=0, column=0, padx=10, pady=10)
        self.btn_ollama = ctk.CTkButton(self.export_frame, text=t("export.ollama"), command=self._ollama_correct, state="disabled")
        self.btn_ollama.grid(row=0, column=1, padx=(0, 10), pady=10)
        self.btn_settings = ctk.CTkButton(
            self.export_frame,
            text=t("bottom.hide_settings") if self.settings_panel_visible else t("bottom.settings"),
            command=self._toggle_settings_panel,
        )
        self.btn_settings.grid(row=0, column=3, padx=10, pady=10)

        self._refresh_project_files_list()

    def _scroll_project_files(self, e):
        """Прокрутка панели «Файлы проекта» колесом мыши."""
        scroll = self._left_panel_files_scroll
        canvas = getattr(scroll, "_parent_canvas", None)
        if not canvas:
            return
        step = 3
        if getattr(e, "delta", None):
            units = -1 * (e.delta // 120) * step if e.delta else 0
        elif e.num == 4:
            units = -step
        elif e.num == 5:
            units = step
        else:
            return
        if units:
            canvas.yview_scroll(units, "units")

    def _bind_project_files_wheel(self):
        """Привязать прокрутку колесом к панели файлов и ко всем текущим дочерним виджетам."""
        def _scroll(e):
            self._scroll_project_files(e)
        scroll = self._left_panel_files_scroll
        scroll.bind("<MouseWheel>", _scroll)
        scroll.bind("<Button-4>", _scroll)
        scroll.bind("<Button-5>", _scroll)
        for w in scroll.winfo_children():
            w.bind("<MouseWheel>", _scroll)
            w.bind("<Button-4>", _scroll)
            w.bind("<Button-5>", _scroll)

    def _refresh_project_files_list(self):
        """Заполнить левую панель списком аудио/видео файлов (новые сверху), выравнивание по левому краю, тултип и контекстное меню."""
        for w in self._left_panel_files_scroll.winfo_children():
            w.destroy()
        if not self.current_project_dir or not os.path.isdir(self.current_project_dir):
            lbl = ctk.CTkLabel(
                self._left_panel_files_scroll, text=t("project_files.no_project"),
                text_color="gray", font=ctk.CTkFont(size=11), wraplength=self._left_panel_width - 24,
            )
            lbl.grid(row=0, column=0, sticky="w", padx=4, pady=8)
            for _scroll_ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                lbl.bind(_scroll_ev, self._scroll_project_files)
            return
        exts = (".mp3", ".mp4", ".wav", ".m4a", ".mkv")
        try:
            names = [f for f in os.listdir(self.current_project_dir)
                     if os.path.isfile(os.path.join(self.current_project_dir, f)) and f.lower().endswith(exts)]
        except Exception:
            names = []
        # Новые файлы вверху: сортировка по дате изменения (убывание), затем по имени
        def _mtime_name(x):
            p = os.path.join(self.current_project_dir, x)
            try:
                return (-os.path.getmtime(p), x.lower())
            except Exception:
                return (0, x.lower())
        names.sort(key=_mtime_name)
        _max_name_len = 36
        for i, name in enumerate(names):
            rel_path = name
            has_transcript = bool(self.file_transcripts.get(rel_path))
            suffix = " \u2713" if has_transcript else ""
            display_text = (name[: _max_name_len - len(suffix) - 1] + "\u2026" + suffix) if len(name) + len(suffix) > _max_name_len else (name + suffix)
            row_f = ctk.CTkFrame(
                self._left_panel_files_scroll, fg_color=("gray80", "gray28") if has_transcript else ("gray85", "gray22"),
                corner_radius=4, cursor="hand2",
            )
            row_f._rel_path = rel_path
            row_f.grid(row=i, column=0, sticky="ew", padx=4, pady=2)
            row_f.grid_columnconfigure(0, weight=1)
            lbl = ctk.CTkLabel(row_f, text=display_text, anchor="w", font=ctk.CTkFont(size=12))
            row_f._label = lbl
            lbl.grid(row=0, column=0, sticky="w", padx=8, pady=6)
            row_f.bind("<Button-1>", lambda e, r=rel_path: self._on_project_file_clicked(r))
            lbl.bind("<Button-1>", lambda e, r=rel_path: self._on_project_file_clicked(r))
            row_f.bind("<Button-3>", lambda e, r=rel_path: self._show_project_file_context_menu(e, r))
            lbl.bind("<Button-3>", lambda e, r=rel_path: self._show_project_file_context_menu(e, r))
            self._bind_tooltip_text(row_f, name)
            self._bind_tooltip_text(lbl, name)
            for _scroll_ev in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                row_f.bind(_scroll_ev, self._scroll_project_files)
                lbl.bind(_scroll_ev, self._scroll_project_files)
        self._left_panel_files_scroll.grid_columnconfigure(0, weight=1)

    def _show_project_file_context_menu(self, event, rel_path: str):
        """Показать контекстное меню для файла в панели «Файлы проекта»: Удалить, Переименовать, Открыть в папке."""
        menu = Menu(self, tearoff=0)
        menu.add_command(label=t("project_files.open_in_folder"), command=lambda: self._project_file_open_in_folder(rel_path))
        menu.add_command(label=t("project_files.rename"), command=lambda: self._project_file_rename(rel_path))
        menu.add_separator()
        menu.add_command(label=t("project_files.delete"), command=lambda: self._project_file_delete(rel_path))
        try:
            menu.tk_popup(event.widget.winfo_rootx() + event.x, event.widget.winfo_rooty() + event.y)
        finally:
            menu.grab_release()

    def _project_file_open_in_folder(self, rel_path: str):
        """Открыть папку с файлом в проводнике и по возможности выделить файл."""
        if not self.current_project_dir:
            return
        abs_path = os.path.normpath(os.path.join(self.current_project_dir, rel_path))
        if not os.path.isfile(abs_path):
            return
        folder = os.path.dirname(abs_path)
        if sys.platform == "win32":
            try:
                # Путь в кавычках, чтобы Проводник открыл папку с файлом и выделил файл (не Документы)
                path_arg = abs_path.replace('"', '""')
                subprocess.Popen(f'explorer /select,"{path_arg}"', shell=True)
            except Exception:
                try:
                    os.startfile(folder)
                except Exception:
                    pass
        elif sys.platform == "darwin":
            try:
                subprocess.Popen(["open", "-R", abs_path])
            except Exception:
                try:
                    subprocess.Popen(["open", folder])
                except Exception:
                    pass
        else:
            try:
                subprocess.Popen(["xdg-open", folder])
            except Exception:
                pass

    def _project_file_rename(self, rel_path: str):
        """Включить режим переименования по месту в панели: подпись заменяется на поле ввода, Enter — применить, Escape — отмена."""
        if not self.current_project_dir:
            return
        abs_path = os.path.normpath(os.path.join(self.current_project_dir, rel_path))
        if not os.path.isfile(abs_path):
            return
        row_f = None
        for w in self._left_panel_files_scroll.winfo_children():
            if getattr(w, "_rel_path", None) == rel_path:
                row_f = w
                break
        if not row_f or not getattr(row_f, "_label", None):
            return
        lbl = row_f._label
        base, ext = os.path.splitext(rel_path)

        def _apply_rename():
            new_name = entry.get().strip()
            entry.destroy()
            lbl.grid(row=0, column=0, sticky="w", padx=8, pady=6)
            if not new_name:
                return
            if not new_name.lower().endswith(ext.lower()):
                new_name += ext
            new_abs = os.path.normpath(os.path.join(self.current_project_dir, new_name))
            if new_abs == abs_path:
                return
            if os.path.exists(new_abs):
                messagebox.showerror(t("project_files.rename"), t("project_files.rename_exists"))
                return
            try:
                os.rename(abs_path, new_abs)
            except Exception as e:
                messagebox.showerror(t("project_files.rename"), str(e))
                return
            if self.file_transcripts.get(rel_path) is not None:
                self.file_transcripts[new_name] = self.file_transcripts.pop(rel_path)
            if self.current_file == abs_path:
                self.current_file = new_abs
                self.lbl_file.configure(text=os.path.basename(new_abs))
            if self.current_session_path:
                self._session_dirty = True
            self._refresh_project_files_list()

        def _cancel_rename():
            entry.destroy()
            lbl.grid(row=0, column=0, sticky="w", padx=8, pady=6)

        lbl.grid_remove()
        entry = ctk.CTkEntry(row_f, font=ctk.CTkFont(size=12))
        entry.insert(0, rel_path)
        entry.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        entry.focus_set()
        entry.select_range(0, "end")
        entry.bind("<Return>", lambda e: _apply_rename())
        entry.bind("<Escape>", lambda e: _cancel_rename())

    def _project_file_delete(self, rel_path: str):
        """Удалить файл из папки проекта (с подтверждением). Удаляется только файл с диска; транскрипт убирается из кэша."""
        if not self.current_project_dir:
            return
        abs_path = os.path.normpath(os.path.join(self.current_project_dir, rel_path))
        if not os.path.isfile(abs_path):
            return
        if not messagebox.askyesno(t("project_files.delete"), t("project_files.delete_confirm", name=rel_path)):
            return
        self.file_transcripts.pop(rel_path, None)
        if self.current_file == abs_path:
            self.current_file = None
            self.full_results = []
            self.lbl_file.configure(text=t("top.no_file_formats"))
            self._show_text_output()
            self.btn_export_txt.configure(state="disabled")
            self.btn_save_session.configure(state="disabled")
            self.btn_ollama.configure(state="disabled")
        try:
            os.remove(abs_path)
        except Exception as e:
            messagebox.showerror(t("project_files.delete"), str(e))
            return
        if self.current_session_path:
            self._session_dirty = True
        self._refresh_project_files_list()

    def _on_project_file_clicked(self, rel_path: str):
        """Переключить текущий файл на выбранный в левой панели и подгрузить его транскрипт."""
        if not self.current_project_dir:
            return
        # Сохранить транскрипт текущего файла в кэш перед переключением (в т.ч. несохранённые правки)
        if self.current_file and self.full_results:
            prev_rel = SessionService._make_path_relative_to_project(
                self.current_file, os.path.join(self.current_project_dir, "_.wiproject")
            )
            self.file_transcripts[prev_rel] = list(self.full_results)
        abs_path = os.path.normpath(os.path.join(self.current_project_dir, rel_path))
        self.current_file = abs_path
        self.full_results = list(self.file_transcripts.get(rel_path, []))
        self.lbl_file.configure(text=os.path.basename(abs_path))
        if self.full_results:
            self._show_segment_editor()
            self._rebuild_segment_list()
            self.btn_export_txt.configure(state="normal")
            self.btn_save_session.configure(state="normal")
            self.btn_ollama.configure(state="normal")
        else:
            self._segment_scroll.grid_remove()
            self.txt_output.grid(row=0, column=0, sticky="nsew")
            self.txt_output.delete("1.0", "end")
            self.btn_export_txt.configure(state="disabled")
            self.btn_save_session.configure(state="disabled")
            self.btn_ollama.configure(state="disabled")
        self._session_dirty = False

    def _on_settings_tab_changed(self, value: str):
        """Показать выбранную вкладку настроек (value — переведённое название)."""
        self._tab_transcription.grid_remove()
        self._tab_glossary.grid_remove()
        self._tab_interface.grid_remove()
        tabs = [t("tabs.transcription"), t("tabs.glossary"), t("tabs.interface")]
        if value == tabs[0]:
            self._settings_tab_index = 0
            self._tab_transcription.grid(row=0, column=0, sticky="nsew")
        elif value == tabs[1]:
            self._settings_tab_index = 1
            self._tab_glossary.grid(row=0, column=0, sticky="nsew")
        else:
            self._settings_tab_index = 2
            self._tab_interface.grid(row=0, column=0, sticky="nsew")

    def _maximize_window(self):
        """Развернуть окно на весь экран (по умолчанию при запуске)."""
        try:
            self.state("zoomed")
        except Exception:
            pass

    def _has_unsaved_work(self):
        """Есть ли несохранённые изменения: есть транскрипция и она менялась после последнего сохранения."""
        return bool(self._session_dirty and self.current_file and self.full_results)

    def _on_close(self):
        """Обработка закрытия окна: при наличии работы предложить сохранить проект."""
        if not self._has_unsaved_work():
            self.destroy()
            return
        try:
            msg = t("close.save_prompt")
        except Exception:
            msg = "Save project before closing?"
        choice = messagebox.askyesnocancel(t("app.title"), msg)
        if choice is None:
            return
        if choice:
            if not self._save_session():
                return
        self.destroy()

    def _bind_tooltip(self, widget, locale_key: str):
        """Показать при наведении подсказку с локализованным текстом t(locale_key)."""
        def _show():
            self._tooltip_after_id = None
            if self._tooltip_win:
                try:
                    self._tooltip_win.destroy()
                except Exception:
                    pass
            try:
                text = t(locale_key)
                self._tooltip_win = Toplevel(self)
                self._tooltip_win.overrideredirect(True)
                self._tooltip_win.wm_attributes("-topmost", True)
                lbl = Label(self._tooltip_win, text=text, background="#333", foreground="#eee",
                            relief="solid", borderwidth=1, padx=6, pady=4, font=("Segoe UI", 9))
                lbl.pack()
                self._tooltip_win.update_idletasks()
                wx, wy = widget.winfo_rootx(), widget.winfo_rooty()
                ww, wh = widget.winfo_width(), widget.winfo_height()
                tw, th = self._tooltip_win.winfo_reqwidth(), self._tooltip_win.winfo_reqheight()
                x = wx + (ww - tw) // 2
                y = wy + wh + 4
                self._tooltip_win.wm_geometry(f"+{x}+{y}")
            except Exception:
                pass

        def _on_enter(e):
            if self._tooltip_after_id:
                self.after_cancel(self._tooltip_after_id)
            self._tooltip_after_id = self.after(500, _show)

        def _on_leave(e):
            if self._tooltip_after_id:
                self.after_cancel(self._tooltip_after_id)
                self._tooltip_after_id = None
            if self._tooltip_win:
                try:
                    self._tooltip_win.destroy()
                    self._tooltip_win = None
                except Exception:
                    self._tooltip_win = None

        widget.bind("<Enter>", _on_enter)
        widget.bind("<Leave>", _on_leave)

    def _bind_tooltip_text(self, widget, text: str):
        """Показать при наведении подсказку с произвольным текстом (например полное имя файла)."""
        if not text:
            return
        def _show():
            self._tooltip_after_id = None
            if self._tooltip_win:
                try:
                    self._tooltip_win.destroy()
                except Exception:
                    pass
            try:
                self._tooltip_win = Toplevel(self)
                self._tooltip_win.overrideredirect(True)
                self._tooltip_win.wm_attributes("-topmost", True)
                lbl = Label(self._tooltip_win, text=text, background="#333", foreground="#eee",
                            relief="solid", borderwidth=1, padx=6, pady=4, font=("Segoe UI", 9))
                lbl.pack()
                self._tooltip_win.update_idletasks()
                wx, wy = widget.winfo_rootx(), widget.winfo_rooty()
                ww, wh = widget.winfo_width(), widget.winfo_height()
                tw, th = self._tooltip_win.winfo_reqwidth(), self._tooltip_win.winfo_reqheight()
                x = wx + (ww - tw) // 2
                y = wy + wh + 4
                self._tooltip_win.wm_geometry(f"+{x}+{y}")
            except Exception:
                pass

        def _on_enter(e):
            if self._tooltip_after_id:
                self.after_cancel(self._tooltip_after_id)
            self._tooltip_after_id = self.after(500, _show)

        def _on_leave(e):
            if self._tooltip_after_id:
                self.after_cancel(self._tooltip_after_id)
                self._tooltip_after_id = None
            if self._tooltip_win:
                try:
                    self._tooltip_win.destroy()
                    self._tooltip_win = None
                except Exception:
                    self._tooltip_win = None

        widget.bind("<Enter>", _on_enter)
        widget.bind("<Leave>", _on_leave)

    def _ensure_panel_geometry(self, open_panel: bool):
        """Расширить или сузить окно при открытии/закрытии правой панели."""
        try:
            w, h = self.winfo_width(), self.winfo_height()
            x, y = self.winfo_x(), self.winfo_y()
        except Exception:
            w, h, x, y = 800, 600, 100, 100
        if open_panel:
            self.grid_columnconfigure(2, minsize=self._right_panel_width)
            self.geometry(f"{w + self._right_panel_width}x{h}+{x}+{y}")
        else:
            self.grid_columnconfigure(2, minsize=0)
            self.geometry(f"{max(400, w - self._right_panel_width)}x{h}+{x}+{y}")

    def _toggle_settings_panel(self):
        """Показать/скрыть правую панель с вкладками (Транскрибация, Глоссарий, Интерфейс)."""
        try:
            w, h = self.winfo_width(), self.winfo_height()
            x, y = self.winfo_x(), self.winfo_y()
        except Exception:
            w, h, x, y = 800, 600, 100, 100
        if self.settings_panel_visible:
            self._right_panel.grid_remove()
            self.settings_panel_visible = False
            self._refresh_ui()
            self._ensure_panel_geometry(False)
        else:
            was_open = self.settings_panel_visible
            self.grid_columnconfigure(2, minsize=self._right_panel_width)
            self._right_panel.grid(row=0, column=2, rowspan=5, padx=(0, 20), pady=(0, 20), sticky="nsew")
            self.settings_panel_visible = True
            self._refresh_ui()
            if not was_open:
                self._ensure_panel_geometry(True)
            # Принудительно обновить scrollregion при открытии (на случай если reqheight был 0 при создании)
            self.after(100, self._force_update_scroll_regions)

    def _force_update_scroll_regions(self):
        """Обновить scrollregion у списка языков и перерисовать кастомный скроллбар."""
        self.update_idletasks()
        try:
            req_h = self._lang_inner.winfo_reqheight()
            box_h, box_w = 140, 260
            if req_h > box_h:
                self._lang_canvas.configure(scrollregion=(0, 0, box_w, req_h))
            self._lang_scrollbar.set(0.0, min(1.0, box_h / max(req_h, 1)))
            self._lang_scrollbar._draw()
        except Exception:
            pass

    def _build_settings_panel(self, parent):
        """Содержимое вкладки Transcription: прокручиваемая область, список языков всегда виден."""
        app = self
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        # Колонка без лишнего отступа; у описаний большой padx слева — иначе CTkScrollableFrame обрезает текст
        win = ctk.CTkFrame(scroll, fg_color="transparent")
        win.grid(row=0, column=0, sticky="nsew", padx=(0, 0), pady=0)
        win.grid_columnconfigure(0, weight=1)

        row = 0
        _hint_font = ctk.CTkFont(size=11)
        _hint_color = ("gray50", "gray55")
        _hr_color = ("gray75", "gray30")

        def _add_hr():
            nonlocal row
            hr = ctk.CTkFrame(win, height=2, fg_color=_hr_color)
            hr.grid(row=row, column=0, sticky="ew", padx=10, pady=(8, 4))
            row += 1

        self._lbl_model = ctk.CTkLabel(win, text=t("settings.model"), font=ctk.CTkFont(weight="bold"))
        self._lbl_model.grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        model_opts = [
            ("tiny", "model.tiny.desc"),
            ("base", "model.base.desc"),
            ("small", "model.small.desc"),
            ("medium", "model.medium.desc"),
            ("large-v3", "model.large_v3.desc"),
        ]
        _cfg = load_config()
        self._settings_model_value = _cfg.get("transcription_model") or "base"
        self._model_selection_label = ctk.CTkLabel(win, text=t("settings.selection", value=self._settings_model_value), font=ctk.CTkFont(weight="bold"), anchor="w")
        self._model_selection_label.grid(row=row, column=0, sticky="w", padx=10, pady=(4, 2))
        row += 1
        _list_block_w = 260
        model_list_container = ctk.CTkFrame(win, fg_color=("gray90", "gray25"))
        self._model_list_container = model_list_container
        model_list_container.grid(row=row, column=0, sticky="ew", padx=10, pady=(0, 8))
        model_list_container.grid_columnconfigure(0, weight=1)
        _model_inner = ctk.CTkFrame(model_list_container, fg_color="transparent")
        _model_inner.pack(fill="x", padx=0, pady=0)
        _model_hover_fg = ("#D6E4FF", "#2A4A6E")
        self._model_row_frames = {}
        self._model_status_labels = {}
        self._model_progress_bars = {}
        self._model_delete_btns = {}
        self._model_downloading = None
        for model_id, model_desc in model_opts:
            row_f = ctk.CTkFrame(_model_inner, fg_color="transparent", corner_radius=4, cursor="hand2")
            row_f.pack(fill="x", padx=4, pady=2)
            self._model_row_frames[model_id] = row_f
            def _row_enter(e, rf=row_f):
                rf.configure(fg_color=_model_hover_fg)
            def _row_leave(e, rf=row_f, mid=model_id):
                def _check():
                    try:
                        if self._settings_model_value == mid:
                            return
                        root = rf.winfo_toplevel()
                        wx, wy = root.winfo_pointerx(), root.winfo_pointery()
                        w = root.winfo_containing(wx, wy)
                        while w and w != rf:
                            w = w.master if hasattr(w, "master") else None
                        if w != rf:
                            rf.configure(fg_color="transparent")
                    except Exception:
                        if self._settings_model_value != mid:
                            rf.configure(fg_color="transparent")
                self.after(20, _check)
            name_lbl = ctk.CTkLabel(row_f, text=model_id, font=ctk.CTkFont(weight="bold"), anchor="w", cursor="hand2")
            name_lbl.pack(fill="x")
            desc_lbl = ctk.CTkLabel(row_f, text=f"({t(model_desc)})", font=_hint_font, text_color=_hint_color, anchor="nw", wraplength=220, justify="left", cursor="hand2")
            desc_lbl.pack(fill="x")
            status_row = ctk.CTkFrame(row_f, fg_color="transparent")
            status_row.pack(fill="x")
            status_lbl = ctk.CTkLabel(status_row, text="", font=ctk.CTkFont(size=11), anchor="w", cursor="hand2", text_color=("gray50", "gray55"))
            status_lbl.pack(side="left", fill="x", expand=True)
            self._model_status_labels[model_id] = status_lbl
            delete_lbl = ctk.CTkLabel(
                status_row, text=t("model.delete"), font=ctk.CTkFont(size=10),
                text_color="#c62828", cursor="hand2", anchor="e",
            )
            delete_lbl.pack(side="right", padx=(4, 0))
            self._model_delete_btns[model_id] = delete_lbl
            def _model_click(e, v=model_id):
                self._on_model_row_clicked(v)
            def _delete_click(e, v=model_id):
                self._delete_model(v)
                return "break"
            delete_lbl.bind("<Button-1>", _delete_click)
            progress_f = ctk.CTkFrame(row_f, fg_color="transparent", height=4)
            progress_f.pack_propagate(False)
            pb = ctk.CTkProgressBar(progress_f, height=4, width=200)
            pb.pack(fill="x")
            pb.set(0)
            self._model_progress_bars[model_id] = (progress_f, pb)
            for w in (row_f, name_lbl, desc_lbl, status_lbl):
                w.bind("<Enter>", _row_enter)
                w.bind("<Leave>", _row_leave)
                w.bind("<Button-1>", _model_click)
        self._refresh_model_status_labels()
        # подсветка выбранной модели
        self._pick_model(self._settings_model_value)
        row += 1
        _add_hr()
        self._lbl_language = ctk.CTkLabel(win, text=t("settings.language"), font=ctk.CTkFont(weight="bold"))
        self._lbl_language.grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        self._lbl_language_hint = ctk.CTkLabel(win, text=t("settings.language_hint"), font=_hint_font, text_color=_hint_color, wraplength=240, justify="left")
        self._lbl_language_hint.grid(row=row, column=0, sticky="w", padx=10, pady=(0, 2))
        row += 1
        saved_code = _cfg.get("transcription_language")  # None = Auto
        if saved_code is not None and not isinstance(saved_code, str):
            saved_code = None
        if saved_code is not None:
            saved_code = str(saved_code).strip().lower() or None
        lang_opts = get_language_combo_values()
        if saved_code is None:
            self._settings_language_value = "Auto"
        else:
            for opt in lang_opts:
                if language_display_to_code(opt) == saved_code:
                    self._settings_language_value = opt
                    break
            else:
                self._settings_language_value = "Auto"
        self._lang_selection_label = ctk.CTkLabel(win, text=t("settings.selection", value=self._settings_language_value), font=ctk.CTkFont(weight="bold"), anchor="w")
        self._lang_selection_label.grid(row=row, column=0, sticky="w", padx=10, pady=(4, 2))
        row += 1
        # Language list: Canvas + inner frame + scrollbar (та же ширина блока, что у списка моделей)
        _lang_box_h, _lang_box_w = 140, _list_block_w
        _scrollbar_w = 16
        lang_list_container = ctk.CTkFrame(win, width=_lang_box_w, height=_lang_box_h, fg_color=("gray90", "gray25"))
        self._lang_list_container = lang_list_container
        lang_list_container.grid(row=row, column=0, sticky="w", padx=10, pady=(0, 8))
        lang_list_container.grid_propagate(False)
        lang_list_container.grid_columnconfigure(0, weight=1)
        _canvas_bg = lang_list_container.cget("fg_color")
        if isinstance(_canvas_bg, tuple):
            _canvas_bg = _canvas_bg[1] if ctk.get_appearance_mode() == "Dark" else _canvas_bg[0]
        _lang_canvas = Canvas(lang_list_container, width=_lang_box_w - _scrollbar_w, height=_lang_box_h, highlightthickness=0, bg=_canvas_bg)
        _lang_canvas.grid(row=0, column=0, sticky="nsew")
        _lang_inner = Frame(_lang_canvas, bg=_canvas_bg)
        _lang_window_id = _lang_canvas.create_window(0, 0, window=_lang_inner, anchor="nw")
        self._lang_canvas = _lang_canvas
        self._lang_inner = _lang_inner
        def _on_lang_frame_configure(e):
            _lang_canvas.configure(scrollregion=_lang_canvas.bbox("all"))
        def _on_lang_canvas_configure(e):
            _lang_canvas.itemconfig(_lang_window_id, width=e.width)
        _lang_inner.bind("<Configure>", _on_lang_frame_configure)
        _lang_canvas.bind("<Configure>", _on_lang_canvas_configure)
        self._lang_scrollbar = DarkScrollbar(lang_list_container, width=_scrollbar_w, height=_lang_box_h,
            command=_lang_canvas.yview, track_color="#505050",
            thumb_color="#1F6AA5", thumb_hover_color="#5DA1D4")
        self._lang_scrollbar.grid(row=0, column=1, sticky="ns")
        _lang_canvas.configure(yscrollcommand=self._lang_scrollbar.set)
        _scroll_step = 5
        def _scroll_lang_list_only(e):
            if hasattr(e, "delta") and e.delta:
                units = int(-1 * (e.delta / 120)) * _scroll_step
            elif getattr(e, "num", None) == 5:
                units = _scroll_step
            elif getattr(e, "num", None) == 4:
                units = -_scroll_step
            else:
                return
            _lang_canvas.yview_scroll(units, "units")
            return "break"
        _lang_canvas.bind("<MouseWheel>", _scroll_lang_list_only)
        _lang_canvas.bind("<Button-4>", _scroll_lang_list_only)
        _lang_canvas.bind("<Button-5>", _scroll_lang_list_only)
        self._scroll_lang_list_only = _scroll_lang_list_only
        self._lang_buttons = {}
        for opt in lang_opts:
            def make_cmd(val):
                return lambda: self._pick_language(val)
            btn = ctk.CTkButton(_lang_inner, text=opt, width=220, anchor="w", fg_color="transparent", command=make_cmd(opt), cursor="hand2")
            btn.pack(fill="x", padx=4, pady=2)
            self._lang_buttons[opt] = btn
            btn.bind("<MouseWheel>", self._scroll_lang_list_only)
            btn.bind("<Button-4>", self._scroll_lang_list_only)
            btn.bind("<Button-5>", self._scroll_lang_list_only)
        # подсветка выбранного языка
        self._pick_language(self._settings_language_value)
        # Явно задать scrollregion (winfo_reqheight работает даже для unmapped виджетов)
        _lang_inner.update_idletasks()
        _req_h_lang = _lang_inner.winfo_reqheight()
        _lang_canvas.configure(scrollregion=(0, 0, _lang_box_w, max(_req_h_lang, _lang_box_h + 1)))
        row += 1
        _add_hr()
        self._lbl_beam_size = ctk.CTkLabel(win, text=t("settings.beam_size"), font=ctk.CTkFont(weight="bold"))
        self._lbl_beam_size.grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        self._lbl_beam_size_hint = ctk.CTkLabel(win, text=t("settings.beam_size_hint"), font=_hint_font, text_color=_hint_color, wraplength=240, justify="left")
        self._lbl_beam_size_hint.grid(row=row, column=0, sticky="w", padx=10, pady=(0, 2))
        row += 1
        beam_row = ctk.CTkFrame(win, fg_color="transparent")
        beam_row.grid(row=row, column=0, sticky="w", padx=10, pady=(0, 8))
        beam_row.grid_columnconfigure(0, weight=1)
        _beam_val = max(1, min(10, int(_cfg.get("transcription_beam_size", 5))))
        self._settings_beam_size = ctk.CTkSlider(beam_row, from_=1, to=10, number_of_steps=9, width=220, command=self._on_beam_size_change)
        self._settings_beam_size.set(_beam_val)
        self._settings_beam_size.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._beam_size_label = ctk.CTkLabel(beam_row, text=str(_beam_val), width=28, font=ctk.CTkFont(weight="bold"))
        self._beam_size_label.grid(row=0, column=1, sticky="w")
        row += 1

        self._settings_vad = ctk.CTkCheckBox(win, text=t("settings.vad"), command=lambda: self._save_transcription_settings())
        if _cfg.get("transcription_vad", True):
            self._settings_vad.select()
        else:
            self._settings_vad.deselect()
        self._settings_vad.grid(row=row, column=0, sticky="w", padx=10, pady=8)
        row += 1
        _add_hr()
        self._lbl_task = ctk.CTkLabel(win, text=t("settings.task"), font=ctk.CTkFont(weight="bold"))
        self._lbl_task.grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        self._lbl_task_hint = ctk.CTkLabel(win, text=t("settings.task_hint"), font=_hint_font, text_color=_hint_color, wraplength=240, justify="left")
        self._lbl_task_hint.grid(row=row, column=0, sticky="w", padx=10, pady=(0, 2))
        row += 1
        self._task_var = StringVar(value=_cfg.get("transcription_task") or "transcribe")
        self._settings_task = ctk.CTkSegmentedButton(win, values=["transcribe", "translate"], variable=self._task_var)
        self._settings_task.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="w")
        row += 1

        self._settings_word_ts = ctk.CTkCheckBox(win, text=t("settings.word_timestamps"), command=lambda: self._save_transcription_settings())
        if _cfg.get("transcription_word_timestamps", False):
            self._settings_word_ts.select()
        else:
            self._settings_word_ts.deselect()
        self._settings_word_ts.grid(row=row, column=0, sticky="w", padx=10, pady=8)
        row += 1
        _add_hr()
        self._lbl_device = ctk.CTkLabel(win, text=t("settings.device"), font=ctk.CTkFont(weight="bold"))
        self._lbl_device.grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        self._device_var = StringVar(value=_cfg.get("transcription_device") or "auto")
        self._settings_device = ctk.CTkSegmentedButton(win, values=["auto", "cuda", "cpu"], variable=self._device_var)
        self._settings_device.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="w")
        row += 1
        _add_hr()
        self._lbl_compute_type = ctk.CTkLabel(win, text=t("settings.compute_type"), font=ctk.CTkFont(weight="bold"))
        self._lbl_compute_type.grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        self._lbl_compute_type_hint = ctk.CTkLabel(win, text=t("settings.compute_type_hint"), font=_hint_font, text_color=_hint_color, wraplength=240, justify="left")
        self._lbl_compute_type_hint.grid(row=row, column=0, sticky="w", padx=10, pady=(0, 2))
        row += 1
        self._compute_var = StringVar(value=_cfg.get("transcription_compute_type") or "float16")
        self._settings_compute = ctk.CTkSegmentedButton(win, values=["float16", "int8"], variable=self._compute_var)
        self._settings_compute.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="w")
        row += 1
        _add_hr()
        self._btn_reset_transcription = ctk.CTkButton(win, text=t("settings.reset_to_default"), fg_color=("gray75", "gray35"), command=self._reset_transcription_settings)
        self._btn_reset_transcription.grid(row=row, column=0, padx=10, pady=(10, 12), sticky="ew")
        row += 1

        self._task_var.trace_add("write", lambda *a: app._save_transcription_settings())
        self._device_var.trace_add("write", lambda *a: app._save_transcription_settings())
        self._compute_var.trace_add("write", lambda *a: app._save_transcription_settings())

        # Не прокручивать панель настроек колёсиком, когда курсор над списками модели или языков
        self._settings_scroll = scroll
        _orig_mouse_wheel = scroll._mouse_wheel_all
        def _mouse_wheel_filter(e):
            w = e.widget
            while w:
                if w == self._model_list_container or w == self._lang_list_container:
                    return
                w = getattr(w, "master", None)
            _orig_mouse_wheel(e)
        scroll._mouse_wheel_all = _mouse_wheel_filter

    def _refresh_ui(self):
        """Обновить все переводимые надписи интерфейса после смены языка."""
        self._update_session_title()
        if not self.current_file:
            self.lbl_file.configure(text=t("top.no_file_formats"))
        self.btn_export_txt.configure(text=t("export.txt"))
        self.btn_ollama.configure(text=t("export.ollama"))
        if hasattr(self, "btn_open_session"):
            self.btn_open_session.configure(text=t("session.open_project"))
        if hasattr(self, "btn_save_session"):
            self.btn_save_session.configure(text=t("session.save_project"))
        if hasattr(self, "btn_start"):
            self.btn_start.configure(text=t("control.start"))
        if hasattr(self, "btn_stop"):
            self.btn_stop.configure(text=t("control.stop"))
        if hasattr(self, "btn_browse"):
            self.btn_browse.configure(text=t("top.browse_file"))
        if hasattr(self, "btn_mic_record"):
            self.btn_mic_record.configure(text=t("top.mic"))
        if hasattr(self, "btn_import_youtube"):
            self.btn_import_youtube.configure(text=t("top.import_youtube"))
        if hasattr(self, "_mic_normal_start_btn"):
            self._mic_normal_start_btn.configure(text=t("import.mic_start"))
            self._mic_normal_stop_btn.configure(text=t("import.mic_stop"))
        if hasattr(self, "_mic_glossary_cb"):
            self._mic_glossary_cb.configure(text=t("mic.use_glossary"))
        if hasattr(self, "_mic_mode_buttons"):
            self._mic_mode_buttons.configure(values=[t("mic.mode_normal"), t("mic.mode_streaming")])
            self._mic_mode_var.set(t("mic.mode_normal") if getattr(self, "_mic_current_mode", "normal") == "normal" else t("mic.mode_streaming"))
        if hasattr(self, "_mic_start_btn"):
            self._mic_start_btn.configure(text=t("import.mic_start"))
        if hasattr(self, "_mic_stop_btn"):
            self._mic_stop_btn.configure(text=t("import.mic_stop"))
        if hasattr(self, "_mic_device_option") and hasattr(self, "_mic_device_list"):
            new_default = t("mic.input_device_default")
            new_values = [new_default] + [n for _, n in self._mic_device_list]
            self._mic_device_option.configure(values=new_values)
            if self._mic_device_var.get() not in new_values:
                self._mic_device_var.set(new_default)
        if hasattr(self, "_mic_gain_software_title"):
            self._mic_gain_software_title.configure(text=t("mic.gain_software"))
        if hasattr(self, "_mic_gain_system_title"):
            self._mic_gain_system_title.configure(text=t("mic.gain_system") if getattr(self, "_mic_system_volume_available", False) else t("mic.gain_system_unavailable"))
        self.btn_settings.configure(
            text=t("bottom.hide_settings") if self.settings_panel_visible else t("bottom.settings")
        )
        # Вкладки настроек: обновить названия и текущую вкладку
        if hasattr(self, "_settings_tab_buttons"):
            tabs = [t("tabs.transcription"), t("tabs.glossary"), t("tabs.interface")]
            self._settings_tab_buttons.configure(values=tabs)
            self._settings_tab_var.set(tabs[self._settings_tab_index])
        # Транскрибация: все надписи
        for key, attr in [
            ("settings.model", "_lbl_model"),
            ("settings.language", "_lbl_language"),
            ("settings.language_hint", "_lbl_language_hint"),
            ("settings.beam_size", "_lbl_beam_size"),
            ("settings.beam_size_hint", "_lbl_beam_size_hint"),
            ("settings.task", "_lbl_task"),
            ("settings.task_hint", "_lbl_task_hint"),
            ("settings.device", "_lbl_device"),
            ("settings.compute_type", "_lbl_compute_type"),
            ("settings.compute_type_hint", "_lbl_compute_type_hint"),
        ]:
            w = getattr(self, attr, None)
            if w:
                w.configure(text=t(key))
        if hasattr(self, "_model_selection_label"):
            self._model_selection_label.configure(text=t("settings.selection", value=self._settings_model_value))
        for model_id, row_f in getattr(self, "_model_row_frames", {}).items():
            key = f"model.{model_id.replace('-', '_')}.desc"
            children = row_f.winfo_children()
            if len(children) >= 2:
                children[1].configure(text=f"({t(key)})")
        if hasattr(self, "_model_status_labels"):
            self._refresh_model_status_labels()
        for btn in getattr(self, "_model_delete_btns", {}).values():
            btn.configure(text=t("model.delete"))
        if hasattr(self, "_lang_buttons"):
            self._rebuild_language_list()
        elif hasattr(self, "_lang_selection_label"):
            self._lang_selection_label.configure(text=t("settings.selection", value=self._settings_language_value))
        if hasattr(self, "_settings_vad"):
            self._settings_vad.configure(text=t("settings.vad"))
        if hasattr(self, "_settings_word_ts"):
            self._settings_word_ts.configure(text=t("settings.word_timestamps"))
        if hasattr(self, "_btn_reset_transcription"):
            self._btn_reset_transcription.configure(text=t("settings.reset_to_default"))
        # Глоссарий
        if hasattr(self, "_glossary_btn_open"):
            self._glossary_btn_open.configure(text=t("glossary.open"))
        if hasattr(self, "_glossary_btn_save"):
            self._glossary_btn_save.configure(text=t("glossary.save"))
        if hasattr(self, "_glossary_lbl_original"):
            self._glossary_lbl_original.configure(text=t("glossary.original"))
        if hasattr(self, "_glossary_lbl_corrected"):
            self._glossary_lbl_corrected.configure(text=t("glossary.corrected"))
        if hasattr(self, "_glossary_btn_add"):
            self._glossary_btn_add.configure(text=t("glossary.update") if self._glossary_editing_original else t("glossary.add"))
        if getattr(self, "_refresh_glossary_list", None):
            self._refresh_glossary_list()
        # Интерфейс: язык UI
        if hasattr(self, "_interface_lang_lbl"):
            self._interface_lang_lbl.configure(text=t("interface.language"))
        if hasattr(self, "_interface_selection_label"):
            self._interface_selection_label.configure(text=t("settings.selection", value=(LANG_FLAGS.get(get_locale(), "") + " " + t(f"lang.{get_locale()}")).strip()))
        for code, rf in getattr(self, "_interface_row_frames", {}).items():
            rf.configure(fg_color=("#D6E4FF", "#2A4A6E") if code == get_locale() else "transparent")
            children = rf.winfo_children()
            if len(children) >= 2:
                children[1].configure(text=t(f"lang.{code}"))

    def _build_interface_settings_panel(self, parent):
        """Вкладка Interface: язык UI в виде списка как Модели (en, es, ru, kk), позже — тема."""
        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        scroll.grid_columnconfigure(0, weight=1)
        win = ctk.CTkFrame(scroll, fg_color="transparent")
        win.grid(row=0, column=0, sticky="nsew", padx=(0, 0), pady=0)
        win.grid_columnconfigure(0, weight=1)

        row = 0
        self._interface_lang_lbl = ctk.CTkLabel(win, text=t("interface.language"), font=ctk.CTkFont(weight="bold"))
        self._interface_lang_lbl.grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        _cur = get_locale()
        self._interface_selection_label = ctk.CTkLabel(
            win, text=t("settings.selection", value=(LANG_FLAGS.get(_cur, "") + " " + t(f"lang.{_cur}")).strip()),
            font=ctk.CTkFont(weight="bold"), anchor="w"
        )
        self._interface_selection_label.grid(row=row, column=0, sticky="w", padx=10, pady=(4, 2))
        row += 1
        interface_list_container = ctk.CTkFrame(win, fg_color=("gray90", "gray25"))
        interface_list_container.grid(row=row, column=0, sticky="ew", padx=10, pady=(0, 8))
        interface_list_container.grid_columnconfigure(0, weight=1)
        interface_inner = ctk.CTkFrame(interface_list_container, fg_color="transparent")
        interface_inner.pack(fill="x", padx=0, pady=0)
        _ui_hover_fg = ("#D6E4FF", "#2A4A6E")
        self._interface_row_frames = {}
        try:
            _flag_font = ctk.CTkFont(family="Segoe UI Emoji", size=16)
        except Exception:
            _flag_font = ctk.CTkFont(size=16)
        _name_font = ctk.CTkFont(weight="bold")
        for code in ["en", "es", "ru", "kk"]:
            row_f = ctk.CTkFrame(interface_inner, fg_color="transparent", corner_radius=4, cursor="hand2")
            row_f.pack(fill="x", padx=4, pady=2)
            self._interface_row_frames[code] = row_f
            flag_lbl = ctk.CTkLabel(row_f, text=LANG_FLAGS.get(code, ""), font=_flag_font, anchor="w", cursor="hand2", width=28)
            flag_lbl.pack(side="left", padx=(4, 0), pady=4)
            lbl = ctk.CTkLabel(row_f, text=t(f"lang.{code}"), font=_name_font, anchor="w", cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True, padx=(6, 8), pady=4)
            def _row_enter(e, rf=row_f):
                rf.configure(fg_color=_ui_hover_fg)
            def _row_leave(e, rf=row_f, c=code):
                def _check():
                    try:
                        if get_locale() == c:
                            return
                        root = rf.winfo_toplevel()
                        wx, wy = root.winfo_pointerx(), root.winfo_pointery()
                        w = root.winfo_containing(wx, wy)
                        while w and w != rf:
                            w = w.master if hasattr(w, "master") else None
                        if w != rf:
                            rf.configure(fg_color="transparent")
                    except Exception:
                        if get_locale() != c:
                            rf.configure(fg_color="transparent")
                self.after(20, _check)
            def _click(e, c=code):
                self._set_ui_locale(c)
            for w in (row_f, flag_lbl, lbl):
                w.bind("<Enter>", _row_enter)
                w.bind("<Leave>", _row_leave)
                w.bind("<Button-1>", _click)
        current = get_locale()
        self._interface_selection_label.configure(text=t("settings.selection", value=(LANG_FLAGS.get(current, "") + " " + t(f"lang.{current}")).strip()))
        for c, rf in self._interface_row_frames.items():
            rf.configure(fg_color=_ui_hover_fg if c == current else "transparent")
        # Место под тему (светлая/тёмная) — позже
        # ctk.CTkLabel(win, text=t("interface.theme")).grid(...)

    def _set_ui_locale(self, code: str):
        """Сменить язык интерфейса, сохранить выбор и обновить надписи."""
        set_locale(code)
        save_locale_preference(code)
        self._refresh_ui()

    def _strip_tail_hallucinations(self, segments):
        """Удалить типичные галлюцинации Whisper в конце: кредиты, «субтитры создавал …», и т.п."""
        if not segments:
            return segments
        # Паттерны фраз-кредитов, которых обычно нет в аудио
        tail_patterns = [
            r"субтитр[ыоа]?\s*(создавал|сделал|by|от)\s*",
            r"subtitles?\s*(created\s*by|by|made\s*by)\s*",
            r"thanks\s*for\s*watching",
            r"подпишись|subscribe",
            r"like\s*and\s*subscribe",
            r"dimatorzok|dima\s*torzok",  # типичная галлюцинация в конце
        ]
        out = list(segments)
        while out:
            last_text = (out[-1].get("text") or "").strip()
            if not last_text:
                out.pop()
                continue
            last_lower = last_text.lower()
            matched = False
            for pat in tail_patterns:
                if re.search(pat, last_lower, re.IGNORECASE | re.UNICODE):
                    matched = True
                    break
            if not matched and ("создавал" in last_lower or "created by" in last_lower):
                matched = True
            if matched:
                out.pop()
            else:
                break
        return out

    def _on_beam_size_change(self, v):
        self._beam_size_label.configure(text=str(int(v)))
        self._save_transcription_settings()

    def _save_transcription_settings(self):
        """Сохранить текущие настройки транскрибации в конфиг."""
        if not hasattr(self, "_task_var"):
            return
        code = language_display_to_code(getattr(self, "_settings_language_value", None) or "Auto")
        save_config({
            "transcription_model": getattr(self, "_settings_model_value", "base"),
            "transcription_language": code,
            "transcription_beam_size": int(self._settings_beam_size.get()) if hasattr(self, "_settings_beam_size") else 5,
            "transcription_vad": bool(self._settings_vad.get()) if hasattr(self, "_settings_vad") else True,
            "transcription_word_timestamps": bool(self._settings_word_ts.get()) if hasattr(self, "_settings_word_ts") else False,
            "transcription_task": self._task_var.get().strip() or "transcribe",
            "transcription_device": self._device_var.get().strip() or "auto",
            "transcription_compute_type": self._compute_var.get().strip() or "float16",
        })

    def _reset_transcription_settings(self):
        """Сбросить настройки транскрибации на значения по умолчанию."""
        defaults = {
            "transcription_model": "base",
            "transcription_language": None,
            "transcription_beam_size": 5,
            "transcription_vad": True,
            "transcription_word_timestamps": False,
            "transcription_task": "transcribe",
            "transcription_device": "auto",
            "transcription_compute_type": "float16",
        }
        save_config(defaults)
        self._settings_model_value = "base"
        self._model_selection_label.configure(text=t("settings.selection", value="base"))
        for mid, rf in getattr(self, "_model_row_frames", {}).items():
            rf.configure(fg_color=("#D6E4FF", "#2A4A6E") if mid == "base" else "transparent")
        self._settings_language_value = "Auto"
        self._lang_selection_label.configure(text=t("settings.selection", value="Auto"))
        if hasattr(self, "_lang_buttons"):
            for val, b in self._lang_buttons.items():
                b.configure(fg_color=("#D6E4FF", "#2A4A6E") if val == "Auto" else "transparent")
        self._settings_beam_size.set(5)
        self._beam_size_label.configure(text="5")
        self._settings_vad.select()
        self._settings_word_ts.deselect()
        self._task_var.set("transcribe")
        self._device_var.set("auto")
        self._compute_var.set("float16")

    def _refresh_model_status_labels(self):
        """Обновить подписи статуса (Скачана X MB/GB или Не скачана) для всех моделей."""
        downloading = getattr(self, "_model_downloading", None)
        status = _get_models_downloaded_status()
        cache_dir = TranscriptionService.get_models_cache_dir()
        for mid, lbl in getattr(self, "_model_status_labels", {}).items():
            if mid == downloading:
                continue
            try:
                if status.get(mid):
                    size_bytes = _get_model_downloaded_size_bytes(cache_dir, mid)
                    size_str = _format_size_bytes(size_bytes) if size_bytes else ""
                    if size_str:
                        text = t("model.status.downloaded_size", size=size_str)
                    else:
                        text = t("model.status.downloaded")
                    lbl.configure(text=text, text_color=("gray40", "gray55"))
                else:
                    lbl.configure(text=t("model.status.not_downloaded"), text_color=("#b85c00", "#e68a00"))
            except Exception:
                pass
        for mid, delete_btn in getattr(self, "_model_delete_btns", {}).items():
            try:
                if mid == downloading or not status.get(mid):
                    delete_btn.pack_forget()
                else:
                    delete_btn.pack(side="right", padx=(4, 0))
            except Exception:
                pass
        for mid, (pf, pb) in getattr(self, "_model_progress_bars", {}).items():
            if mid == downloading:
                continue
            try:
                pb.pack_forget()
                pf.pack_forget()
            except Exception:
                pass

    def _set_model_download_progress(self, model_id: str, n: float, total: float):
        """Обновить прогресс загрузки модели (вызывается из главного потока)."""
        if model_id != getattr(self, "_model_downloading", None):
            return
        try:
            lbl = self._model_status_labels.get(model_id)
            pf, pb = self._model_progress_bars.get(model_id, (None, None))
            if lbl and pf and pb:
                if total and total > 0:
                    pct = min(100, max(0, int(100 * n / total)))
                    lbl.configure(text=t("model.status.downloading", pct=pct), text_color=("gray30", "gray60"))
                    pf.pack(fill="x", pady=(0, 2))
                    pb.pack(fill="x")
                    pb.set(n / total)
                else:
                    lbl.configure(text=t("model.status.downloading", pct=0), text_color=("gray30", "gray60"))
        except Exception:
            pass

    def _on_model_row_clicked(self, model_id: str):
        """Клик по строке модели: если скачана — выбор; если нет — запуск загрузки с прогрессом."""
        status = _get_models_downloaded_status()
        if status.get(model_id):
            self._pick_model(model_id)
            return
        if getattr(self, "_model_downloading", None) is not None:
            messagebox.showinfo(t("app.title"), t("model.status.wait_downloading"))
            return
        self._model_downloading = model_id
        repo_id = MODEL_SIZE_TO_REPO.get(model_id)
        if not repo_id:
            self._model_downloading = None
            return
        cache_dir = TranscriptionService.get_models_cache_dir()
        os.makedirs(cache_dir, exist_ok=True)

        app = self
        mid = model_id

        def run_download():
            err = None
            try:
                import inspect
                import huggingface_hub as hfh
                from tqdm import tqdm as base_tqdm

                # Прогресс-бар для UI: передаём в главный поток n/total; фильтруем kwargs,
                # чтобы не передавать name= (его не принимает старый tqdm) и прочие лишние аргументы
                try:
                    _valid_tqdm_params = set(inspect.signature(base_tqdm.__init__).parameters) - {"self"}
                except Exception:
                    _valid_tqdm_params = {"iterable", "desc", "total", "leave", "file", "ncols", "mininterval", "maxinterval", "miniters", "ascii", "disable", "unit", "unit_scale", "dynamic_ncols", "smoothing", "bar_format", "initial", "position", "postfix", "unit_divisor", "write_stdout", "lock_args", "nrows", "colour", "delay"}

                class ProgressTqdm(base_tqdm):
                    def __init__(self, *args, **kwargs):
                        kwargs = dict(kwargs)
                        if "name" in kwargs:
                            kwargs.setdefault("desc", kwargs.pop("name"))
                        kwargs = {k: v for k, v in kwargs.items() if k in _valid_tqdm_params}
                        super().__init__(*args, **kwargs)

                    def update(self, n=1):
                        super().update(n)
                        if self.total and self.total > 0:
                            nn, tt = self.n, self.total
                            app.after(0, lambda: app._set_model_download_progress(mid, nn, tt))

                allow_patterns = ["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"]
                hfh.snapshot_download(
                    repo_id=repo_id,
                    cache_dir=cache_dir,
                    allow_patterns=allow_patterns,
                    tqdm_class=ProgressTqdm,
                )
            except Exception as e:
                err = str(e) or "Download failed"

            def done():
                app._model_downloading = None
                app._refresh_model_status_labels()
                if err:
                    messagebox.showerror(t("app.title"), err)
                else:
                    app._pick_model(mid)

            app.after(0, done)

        threading.Thread(target=run_download, daemon=True).start()
        self._set_model_download_progress(model_id, 0, 1)

    def _delete_model(self, model_id):
        """Удалить модель с диска (если скачана)."""
        mid = model_id
        if not mid or mid not in MODEL_SIZE_TO_REPO:
            return
        status = _get_models_downloaded_status()
        if not status.get(mid):
            messagebox.showinfo(t("app.title"), t("model.delete_not_downloaded"))
            return
        cache_dir = TranscriptionService.get_models_cache_dir()
        size_bytes = _get_model_downloaded_size_bytes(cache_dir, mid)
        size_str = _format_size_bytes(size_bytes) if size_bytes else ""
        msg = t("model.delete_confirm", model=mid, size=size_str) if size_str else t("model.delete_confirm_short", model=mid)
        if not messagebox.askyesno(t("app.title"), msg):
            return
        folder = os.path.join(cache_dir, f"models--Systran--faster-whisper-{mid}")
        try:
            if os.path.isdir(folder):
                shutil.rmtree(folder)
            self._refresh_model_status_labels()
            messagebox.showinfo(t("app.title"), t("model.delete_done"))
            if mid == getattr(self, "_settings_model_value", None):
                self.service.model = None
        except Exception as e:
            messagebox.showerror(t("app.title"), str(e) or t("model.delete_error"))

    def _pick_model(self, value):
        """Update the model selection label and highlight the selected row."""
        self._settings_model_value = value
        self._model_selection_label.configure(text=t("settings.selection", value=value))
        _sel_fg = ("#D6E4FF", "#2A4A6E")
        for mid, rf in getattr(self, "_model_row_frames", {}).items():
            rf.configure(fg_color=_sel_fg if mid == value else "transparent")
        self._save_transcription_settings()

    def _pick_language(self, display_value):
        """Update the language selection label and highlight the selected button."""
        self._settings_language_value = display_value
        self._lang_selection_label.configure(text=t("settings.selection", value=display_value))
        _sel_fg = ("#D6E4FF", "#2A4A6E")
        for val, b in getattr(self, "_lang_buttons", {}).items():
            b.configure(fg_color=_sel_fg if val == display_value else "transparent")
        self._save_transcription_settings()

    def _rebuild_language_list(self):
        """Пересобрать список языков транскрипции (перевод и сортировка по текущей локали)."""
        saved_code = language_display_to_code(getattr(self, "_settings_language_value", None) or "Auto")
        for btn in getattr(self, "_lang_buttons", {}).values():
            btn.destroy()
        self._lang_buttons.clear()
        lang_opts = get_language_combo_values()
        if saved_code is None:
            self._settings_language_value = "Auto"
        else:
            for opt in lang_opts:
                if language_display_to_code(opt) == saved_code:
                    self._settings_language_value = opt
                    break
            else:
                self._settings_language_value = "Auto"
        scroll_cb = getattr(self, "_scroll_lang_list_only", None)
        for opt in lang_opts:
            def make_cmd(val):
                return lambda: self._pick_language(val)
            btn = ctk.CTkButton(
                self._lang_inner, text=opt, width=220, anchor="w", fg_color="transparent",
                command=make_cmd(opt), cursor="hand2"
            )
            btn.pack(fill="x", padx=4, pady=2)
            self._lang_buttons[opt] = btn
            if scroll_cb:
                btn.bind("<MouseWheel>", scroll_cb)
                btn.bind("<Button-4>", scroll_cb)
                btn.bind("<Button-5>", scroll_cb)
        self._lang_selection_label.configure(text=t("settings.selection", value=self._settings_language_value))
        self._pick_language(self._settings_language_value)
        self._lang_inner.update_idletasks()
        self._force_update_scroll_regions()

    def _save_session(self, force_dialog=False):
        """Сохранить проект. Возвращает True если сохранено, False если пользователь отменил.
        Если открыт проект (current_session_path) и не force_dialog — сохраняет в тот же файл без диалога."""
        if not self.current_file or not self.full_results:
            messagebox.showwarning("Warning", "No transcription to save. Select a file and run transcription first.")
            return False
        path = None
        if not force_dialog and self.current_session_path:
            path = self.current_session_path
        if not path:
            suggested = os.path.splitext(os.path.basename(self.current_file))[0] + ".wiproject"
            initialdir = self.current_project_dir if self.current_project_dir else None
            path = filedialog.asksaveasfilename(
                defaultextension=".wiproject",
                initialfile=suggested,
                initialdir=initialdir,
                filetypes=[("Whisper project", "*.wiproject"), ("All files", "*.*")]
            )
        if not path:
            return False
        # If audio is outside project dir (e.g. temp from YouTube/mic), copy into project folder
        project_dir = os.path.dirname(os.path.abspath(path))
        current_abs = os.path.abspath(self.current_file)
        try:
            current_in_project = os.path.commonpath([project_dir, current_abs]) == project_dir
        except ValueError:
            current_in_project = False  # different drives on Windows
        if not current_in_project:
            dest_name = os.path.basename(self.current_file)
            dest_path = os.path.join(project_dir, dest_name)
            if os.path.exists(dest_path) and os.path.abspath(dest_path) != current_abs:
                base, ext = os.path.splitext(dest_name)
                for i in range(1, 1000):
                    dest_path = os.path.join(project_dir, f"{base}_{i}{ext}")
                    if not os.path.exists(dest_path):
                        break
            try:
                shutil.copy2(self.current_file, dest_path)
                self.current_file = dest_path
            except Exception as e:
                messagebox.showerror("Error", f"Could not copy audio to project folder: {e}")
                return False
        transcript_for_save = [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in self.full_results
        ]
        project_dir = os.path.dirname(os.path.abspath(path))
        current_rel = SessionService._make_path_relative_to_project(self.current_file, path)
        if path == self.current_session_path and self.current_project_dir == project_dir:
            file_transcripts_to_save = dict(self.file_transcripts)
        else:
            file_transcripts_to_save = {}
        file_transcripts_to_save[current_rel] = transcript_for_save
        session = SessionService.build_session(
            audio_path=self.current_file,
            transcript=transcript_for_save,
            model_used=self._settings_model_value,
            glossary_path=self.current_glossary_path,
            project_path=path,
            file_transcripts=file_transcripts_to_save,
            current_file_rel=current_rel,
        )
        if SessionService.save_session(path, session):
            self.current_session_path = path
            self.current_project_dir = project_dir
            self.file_transcripts = file_transcripts_to_save
            self._session_dirty = False
            self._update_session_title()
            self._refresh_project_files_list()
            messagebox.showinfo("Success", f"Session saved: {path}")
            return True
        messagebox.showerror("Error", "Failed to save session.")
        return False

    def _open_session(self):
        initialdir = self.current_project_dir if self.current_project_dir else None
        path = filedialog.askopenfilename(
            title=t("start.open_project"),
            initialdir=initialdir,
            filetypes=[("Whisper project", "*.wiproject"), ("All files", "*.*")]
        )
        if not path:
            return
        self._open_session_with_path(path)

    def _open_session_with_path(self, path: str):
        session = SessionService.load_session(path)
        if not session:
            messagebox.showerror("Error", "Failed to load session or invalid file.")
            return
        if not os.path.exists(session.audio_path):
            messagebox.showwarning(
                "Audio file not found",
                f"The audio file was not found:\n{session.audio_path}\n\nTranscript will be loaded, but you won't be able to re-transcribe without the file."
            )
        self.file_transcripts = getattr(session, "file_transcripts", None) or {}
        self.current_file = session.audio_path
        self.full_results = session.transcript
        self.lbl_file.configure(text=os.path.basename(session.audio_path))
        if session.model_used and session.model_used in ("tiny", "base", "small", "medium", "large-v3"):
            self._pick_model(session.model_used)
        self.full_results = session.transcript
        self._show_segment_editor()
        self._rebuild_segment_list()
        if session.transcript:
            self.btn_export_txt.configure(state="normal")
            self.btn_save_session.configure(state="normal")
            self.btn_ollama.configure(state="normal")
        else:
            self.btn_export_txt.configure(state="disabled")
            self.btn_save_session.configure(state="disabled")
            self.btn_ollama.configure(state="disabled")
        self.current_session_path = path
        self.current_project_dir = os.path.dirname(os.path.abspath(path))
        self._session_dirty = False
        self._update_session_title()
        self._refresh_project_files_list()
        self.current_glossary_path = session.glossary_path
        if session.glossary_path and os.path.exists(session.glossary_path):
            loaded = GlossaryService.load(session.glossary_path)
            self.current_glossary = loaded if loaded else None
        else:
            self.current_glossary = None

    def _build_glossary_panel(self, parent):
        """Собирает содержимое вкладки Glossary."""
        win = parent

        # Top: Open, Save
        top_f = ctk.CTkFrame(win, fg_color="transparent")
        top_f.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        top_f.grid_columnconfigure(1, weight=1)

        # Scrollable list
        list_frame = ctk.CTkScrollableFrame(win, fg_color="transparent")
        list_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)
        list_frame.grid_columnconfigure(0, weight=1)

        def _on_row_click(orig: str, corr: str):
            """Клик по паре в списке: подставить в поля и переключить кнопку на Update."""
            self._glossary_entry_original.delete(0, "end")
            self._glossary_entry_original.insert(0, orig)
            self._glossary_entry_corrected.delete(0, "end")
            self._glossary_entry_corrected.insert(0, corr)
            self._glossary_editing_original = orig
            self._glossary_btn_add.configure(text=t("glossary.update"))

        def _clear_edit_mode():
            self._glossary_editing_original = None
            self._glossary_btn_add.configure(text=t("glossary.add"))
            self._glossary_entry_original.delete(0, "end")
            self._glossary_entry_corrected.delete(0, "end")

        def refresh_list():
            for w in list_frame.winfo_children():
                w.destroy()
            g = self.current_glossary
            if not g or not g.entries:
                ctk.CTkLabel(list_frame, text="(no entries)", text_color="gray").grid(row=0, column=0, sticky="w", padx=0, pady=2)
                return
            for i, e in enumerate(g.entries):
                row_f = ctk.CTkFrame(list_frame, fg_color="transparent")
                row_f.grid(row=i, column=0, sticky="ew", pady=2)
                row_f.grid_columnconfigure(0, weight=1)
                lbl = ctk.CTkLabel(row_f, text=f"{e.original} → {e.corrected}", anchor="w", cursor="hand2")
                lbl.grid(row=0, column=0, sticky="ew", padx=(0, 5))
                o, c = e.original, e.corrected
                lbl.bind("<Button-1>", lambda ev, orig=o, corr=c: _on_row_click(orig, corr))
                row_f.bind("<Button-1>", lambda ev, orig=o, corr=c: _on_row_click(orig, corr))
                orig = e.original
                ctk.CTkButton(row_f, text=t("glossary.delete"), width=60, command=lambda o=orig: _do_delete(o)).grid(row=0, column=1)

        def _do_delete(original: str):
            if not self.current_glossary:
                return
            self.current_glossary = GlossaryService.remove_entry(self.current_glossary, original)
            refresh_list()

        self._refresh_glossary_list = refresh_list

        def do_open():
            path = filedialog.askopenfilename(
                filetypes=[("Glossary JSON", "*.json *.wiglossary"), ("All files", "*.*")]
            )
            if not path:
                return
            g = GlossaryService.load(path)
            if g is None:
                messagebox.showerror("Error", "Failed to load glossary.")
                return
            self.current_glossary = g
            self.current_glossary_path = path
            refresh_list()

        def do_save():
            path = self.current_glossary_path
            if not path:
                path = filedialog.asksaveasfilename(
                    defaultextension=".json",
                    filetypes=[("Glossary JSON", "*.json *.wiglossary"), ("All files", "*.*")]
                )
            if not path:
                return
            g = self.current_glossary if self.current_glossary else GlossaryData()
            if not GlossaryService.save(path, g):
                messagebox.showerror("Error", "Failed to save glossary.")
                return
            self.current_glossary_path = path
            self.current_glossary = g
            messagebox.showinfo("Success", "Glossary saved.")

        self._glossary_btn_open = ctk.CTkButton(top_f, text=t("glossary.open"), command=do_open)
        self._glossary_btn_open.grid(row=0, column=0, padx=(0, 5), pady=0)
        self._glossary_btn_save = ctk.CTkButton(top_f, text=t("glossary.save"), command=do_save)
        self._glossary_btn_save.grid(row=0, column=1, padx=0, pady=0)

        # Bottom: Original, Corrected, Add / Update
        self._glossary_editing_original = None
        bottom_f = ctk.CTkFrame(win, fg_color="transparent")
        bottom_f.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        bottom_f.grid_columnconfigure(1, weight=1)

        self._glossary_entry_original = ctk.CTkEntry(bottom_f)
        self._glossary_entry_corrected = ctk.CTkEntry(bottom_f)
        self._glossary_lbl_original = ctk.CTkLabel(bottom_f, text=t("glossary.original"))
        self._glossary_lbl_original.grid(row=0, column=0, padx=(0, 5), pady=3, sticky="e")
        self._glossary_entry_original.grid(row=0, column=1, padx=0, pady=3, sticky="ew")
        self._glossary_lbl_corrected = ctk.CTkLabel(bottom_f, text=t("glossary.corrected"))
        self._glossary_lbl_corrected.grid(row=1, column=0, padx=(0, 5), pady=3, sticky="e")
        self._glossary_entry_corrected.grid(row=1, column=1, padx=0, pady=3, sticky="ew")

        def do_add_or_update():
            orig = self._glossary_entry_original.get().strip()
            corr = self._glossary_entry_corrected.get().strip()
            if not orig:
                messagebox.showwarning("Warning", "Enter Original text.")
                return
            if not self.current_glossary:
                self.current_glossary = GlossaryData()
            editing = self._glossary_editing_original
            if editing is not None:
                # Режим исправления: удалить старую запись (если ключ изменился) и добавить/обновить
                if editing != orig:
                    self.current_glossary = GlossaryService.remove_entry(self.current_glossary, editing)
                self.current_glossary = GlossaryService.add_entry(self.current_glossary, orig, corr)
                _clear_edit_mode()
            else:
                self.current_glossary = GlossaryService.add_entry(self.current_glossary, orig, corr)
                self._glossary_entry_original.delete(0, "end")
                self._glossary_entry_corrected.delete(0, "end")
            refresh_list()

        self._glossary_btn_add = ctk.CTkButton(bottom_f, text=t("glossary.add"), command=do_add_or_update)
        self._glossary_btn_add.grid(row=2, column=1, pady=(8, 0), sticky="w")
        refresh_list()

    def _update_session_title(self):
        """Обновляет заголовок окна: имя файла проекта, папка проекта или название приложения."""
        if self.current_session_path:
            self.title(os.path.basename(self.current_session_path))
        elif self.current_project_dir:
            self.title(f"{os.path.basename(self.current_project_dir)} — {t('app.title')}")
        else:
            self.title(t("app.title"))

    def _browse_file(self):
        file_path = filedialog.askopenfilename(
            title="Select audio or video file",
            filetypes=[("Media files", "*.mp3 *.mp4 *.wav *.m4a *.mkv"), ("All files", "*.*")]
        )
        if file_path:
            self.current_file = file_path
            self.lbl_file.configure(text=os.path.basename(file_path))

    def _toggle_youtube_panel(self):
        """Показать или скрыть панель вставки ссылки YouTube под панелью управления."""
        if self._youtube_panel_visible:
            self._youtube_frame.grid_remove()
            self._youtube_panel_visible = False
        else:
            self._youtube_frame.grid()
            self._youtube_panel_visible = True

    def _youtube_entry_paste_by_keycode(self, event):
        """Paste from clipboard on Ctrl+V by keycode so it works with any keyboard layout."""
        if event.keycode != 86:
            return
        if not (event.state & 0x4):
            return
        try:
            text = self.clipboard_get()
        except Exception:
            return
        if not text:
            return
        ent = self._youtube_entry
        try:
            ent.delete("sel.first", "sel.last")
        except Exception:
            pass
        ent.insert("insert", text)
        return "break"

    def _load_from_youtube(self):
        url = (self._youtube_entry.get() or "").strip()
        if not url:
            messagebox.showwarning("YouTube", t("import.youtube_url_required"))
            return
        if not YouTubeDownloadService.is_youtube_url(url):
            messagebox.showwarning("YouTube", t("import.youtube_invalid_url"))
            return
        self.btn_youtube_load.configure(state="disabled")
        self._youtube_entry.configure(state="disabled")
        self.lbl_file.configure(text=t("import.youtube_downloading"))
        self.progress_bar.set(0)

        def run():
            def progress(pct: Optional[float], status: str) -> None:
                if pct is not None:
                    self.after(0, lambda: self.progress_bar.set(pct))
                self.after(0, lambda: self.lbl_file.configure(
                    text=t("import.youtube_downloading") + (f" {int((pct or 0) * 100)}%" if pct is not None else "")
                ))

            output_dir = self.current_project_dir if self.current_project_dir else None
            path, err = YouTubeDownloadService.download_audio(url, output_dir=output_dir, progress_callback=progress)
            def done():
                self._youtube_entry.configure(state="normal")
                self.btn_youtube_load.configure(state="normal")
                if err:
                    self.lbl_file.configure(text=t("top.no_file_formats"))
                    self.progress_bar.set(0)
                    messagebox.showerror("YouTube", err)
                    return
                self.current_file = path
                self.lbl_file.configure(text=os.path.basename(path))
                self.progress_bar.set(1.0)
            self.after(0, done)

        threading.Thread(target=run, daemon=True).start()

    def _show_mic_panel(self):
        """Показать или скрыть панель записи (повторный клик по микрофону закрывает панель)."""
        if self._mic_panel_visible:
            self._hide_mic_panel()
            return
        if not self.mic_record.is_available():
            messagebox.showwarning("Microphone", t("import.mic_install_hint"))
            return
        try:
            import soundfile as sf  # noqa: F401
        except ImportError:
            pass
        self._mic_panel_visible = True
        self._sync_mic_glossary_ui_from_mode()
        self._update_mic_status_for_mode()
        self._recording_panel_container.grid(row=4, column=1, padx=20, pady=(0, 8), sticky="w")
        self._update_mic_panel_width()

    def _update_mic_panel_width(self, event=None):
        """Адаптивная ширина панели микрофона: на всю ширину, если места меньше номинальной ширины."""
        if event is not None and getattr(event, "widget", None) is not None and event.widget != self:
            return
        if not getattr(self, "_mic_panel_visible", False):
            return
        try:
            cont = getattr(self, "_recording_panel_container", None)
            if not cont:
                return
            if not cont.winfo_exists():
                return
            available = self.control_frame.winfo_width()
            if available <= 1:
                available = self.winfo_width() - getattr(self, "_left_panel_width", 220) - getattr(self, "_right_panel_width", 320) - 80
            sticky = "ew" if available < getattr(self, "_mic_panel_nominal_width", 720) else "w"
            cont.grid(row=4, column=1, padx=20, pady=(0, 8), sticky=sticky)
        except Exception:
            pass

    def _hide_mic_panel(self):
        """Закрыть панель микрофона; при активной записи — сначала остановить."""
        if self._mic_current_mode == "normal" and self.mic_record.is_recording():
            self._on_mic_normal_stop()
        elif getattr(self, "_mic_streaming_stop_flag", None) is not None:
            self._stop_streaming_if_running()
        self._mic_panel_visible = False
        self._recording_panel_container.grid_remove()

    def _on_mic_mode_changed(self, value: str):
        """Переключение режима: обычная / потоковая. Чекбокс глоссария привязан к выбранному режиму."""
        self._save_mic_glossary_ui_to_mode()
        if value == t("mic.mode_normal"):
            self._mic_current_mode = "normal"
            if getattr(self, "_mic_streaming_stop_flag", None) is not None:
                self._stop_streaming_if_running()
        else:
            self._mic_current_mode = "streaming"
            if self.mic_record.is_recording() and getattr(self, "_mic_normal_timer_job", None):
                self._on_mic_normal_stop()
        self._sync_mic_glossary_ui_from_mode()
        self._update_mic_status_for_mode()
        self._mic_start_btn.configure(state="normal")
        self._mic_stop_btn.configure(state="disabled")
        self._mic_timer.configure(text="00:00")

    def _save_mic_glossary_ui_to_mode(self):
        if self._mic_current_mode == "normal":
            self._mic_normal_use_glossary_var.set(self._mic_glossary_ui_var.get())
        else:
            self._mic_streaming_use_glossary_var.set(self._mic_glossary_ui_var.get())

    def _sync_mic_glossary_ui_from_mode(self):
        if self._mic_current_mode == "normal":
            self._mic_glossary_ui_var.set(self._mic_normal_use_glossary_var.get())
        else:
            self._mic_glossary_ui_var.set(self._mic_streaming_use_glossary_var.get())

    def _update_mic_status_for_mode(self):
        if self._mic_current_mode == "normal":
            self._mic_status.configure(text="")
        else:
            self._mic_status.configure(text=t("mic.press_start"))

    def _get_mic_device_index(self) -> Optional[int]:
        """Индекс выбранного устройства ввода или None для устройства по умолчанию."""
        sel = self._mic_device_var.get()
        if sel == t("mic.input_device_default"):
            return None
        for idx, name in self._mic_device_list:
            if name == sel:
                return idx
        return None

    def _on_mic_device_changed(self, value: str):
        """Обновление выбора устройства ввода (при необходимости можно синхронизировать с системной громкостью)."""
        pass

    def _on_mic_software_gain_changed(self, value):
        v = float(value)
        self.mic_record.set_gain(v)
        self._mic_software_label.configure(text="%d%%" % round(v * 100))

    def _on_mic_system_volume_changed(self, value):
        v = float(value)
        self._mic_system_pct_label.configure(text="%d%%" % round(v * 100))
        if not getattr(self, "_mic_system_volume_available", False):
            return
        try:
            if sys.platform == "win32":
                from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
                from comtypes import CLSCTX_ALL
                devices = AudioUtilities.GetMicrophone()
                if devices:
                    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = interface.QueryInterface(IAudioEndpointVolume)
                    volume.SetMasterVolumeLevelScalar(v, None)
        except Exception:
            pass

    def _stop_streaming_if_running(self):
        self._mic_panel_visible = False
        if getattr(self, "_mic_streaming_waveform_job", None) is not None:
            try:
                self.after_cancel(self._mic_streaming_waveform_job)
                self._mic_streaming_waveform_job = None
            except Exception:
                pass
        if getattr(self, "_mic_streaming_stop_flag", None) is not None:
            self._mic_streaming_stop_flag.append(True)
            self._mic_streaming_worker_done.wait(timeout=10.0)
            if getattr(self, "_mic_streaming_timer_job", [None])[0] is not None:
                try:
                    self.after_cancel(self._mic_streaming_timer_job[0])
                    self._mic_streaming_timer_job[0] = None
                except Exception:
                    pass
            output_dir = self.current_project_dir if self.current_project_dir else tempfile.gettempdir()
            path, err = self.mic_record.stop_and_save(output_dir=output_dir)
            if not err and path:
                self.current_file = path
                self.lbl_file.configure(text=os.path.basename(path))
                self.full_results = list(getattr(self, "_mic_streaming_results", []))
                if self.current_project_dir:
                    rel = SessionService._make_path_relative_to_project(
                        path, os.path.join(self.current_project_dir, "_.wiproject")
                    )
                    self.file_transcripts[rel] = list(self.full_results)
                    self._refresh_project_files_list()
                self._session_dirty = True
                self._show_segment_editor()
                self._rebuild_segment_list()
                self.btn_export_txt.configure(state="normal")
                self.btn_save_session.configure(state="normal")
                self.btn_ollama.configure(state="normal")
        self._mic_panel_visible = True

    def _on_mic_start(self):
        self._save_mic_glossary_ui_to_mode()
        if self._mic_current_mode == "normal":
            self._on_mic_normal_start()
        else:
            self._on_mic_streaming_start()

    def _on_mic_stop(self):
        if self._mic_current_mode == "normal":
            self._on_mic_normal_stop()
        else:
            self._on_mic_streaming_stop()

    def _on_mic_normal_start(self):
        self.mic_record.set_gain(self._mic_software_gain.get())
        err = self.mic_record.start_recording(device=self._get_mic_device_index())
        if err:
            messagebox.showerror("Microphone", err)
            return
        self._mic_normal_elapsed[0] = 0.0
        self._mic_timer.configure(text="00:00")
        self._mic_start_btn.configure(state="disabled")
        self._mic_stop_btn.configure(state="normal")

        def update_timer():
            self._mic_normal_elapsed[0] += 1.0
            m = int(self._mic_normal_elapsed[0]) // 60
            s = int(self._mic_normal_elapsed[0]) % 60
            self._mic_timer.configure(text=f"{m:02d}:{s:02d}")
            if self.mic_record.is_recording():
                self._mic_normal_timer_job = self.after(1000, update_timer)

        def update_waveform():
            if self.mic_record.is_recording():
                try:
                    self._draw_waveform()
                except Exception:
                    pass
                self._mic_normal_waveform_job = self.after(80, update_waveform)

        self._mic_normal_timer_job = self.after(1000, update_timer)
        self._mic_normal_waveform_job = self.after(80, update_waveform)

    def _on_mic_normal_stop(self):
        if self._mic_normal_timer_job:
            self.after_cancel(self._mic_normal_timer_job)
            self._mic_normal_timer_job = None
        if getattr(self, "_mic_normal_waveform_job", None):
            self.after_cancel(self._mic_normal_waveform_job)
            self._mic_normal_waveform_job = None
        output_dir = self.current_project_dir if self.current_project_dir else None
        path, err = self.mic_record.stop_and_save(output_dir=output_dir)
        self._mic_start_btn.configure(state="normal")
        self._mic_stop_btn.configure(state="disabled")
        self._mic_normal_elapsed[0] = 0.0
        self._mic_timer.configure(text="00:00")
        if err:
            messagebox.showerror("Microphone", err)
            return
        self.current_file = path
        self.lbl_file.configure(text=os.path.basename(path))
        if self.current_project_dir and path and os.path.normpath(os.path.dirname(path)) == os.path.normpath(os.path.abspath(self.current_project_dir)):
            self._refresh_project_files_list()

    def _draw_waveform(self):
        """Отрисовать форму волны по последним сэмплам с микрофона."""
        try:
            data = self.mic_record.get_waveform_tail(max_samples=2000)
        except Exception:
            return
        canvas = self._waveform_canvas_mic
        w = max(1, canvas.winfo_width() or 360)
        h = max(1, canvas.winfo_height() or 48)
        canvas.delete("all")
        if data is None or len(data) == 0:
            canvas.create_line(0, h // 2, w, h // 2, fill="#555555", width=1)
            return
        try:
            import numpy as np
            data = np.asarray(data).ravel()
        except Exception:
            return
        n = len(data)
        if n > 1:
            step = max(1, n // max(1, w))
            pts = []
            mid = h / 2
            amp = (h / 2) * 0.9
            gain = 90.0
            for i in range(0, n, step):
                x = (i / n) * w
                s = float(data[i])
                s = max(-1.0, min(1.0, s * gain))
                y = mid - s * amp
                pts.append((x, y))
            if len(pts) >= 2:
                for j in range(len(pts) - 1):
                    canvas.create_line(pts[j][0], pts[j][1], pts[j + 1][0], pts[j + 1][1], fill="#4fc3f7", width=1)
        else:
            canvas.create_line(0, h // 2, w, h // 2, fill="#555555", width=1)

    def _on_mic_streaming_start(self):
        """По нажатию Старт в потоковой записи: загрузка модели и старт записи. Текст — в основной редактор."""
        self._mic_status.configure(text=t("mic.loading_model"))
        self._mic_start_btn.configure(state="disabled")
        self._mic_stop_btn.configure(state="normal")
        self._mic_streaming_stop_flag = []
        self._mic_streaming_worker_done = threading.Event()
        self.txt_output.delete("1.0", "end")
        self._segment_scroll.grid_remove()
        self.txt_output.grid(row=0, column=0, sticky="nsew")
        self._start_mic_streaming_worker()

    # Interval (seconds) for streaming mic: take chunks and transcribe
    _STREAMING_CHUNK_INTERVAL_SEC = 4

    def _start_mic_streaming_worker(self):
        """Запуск потоковой записи: загрузка модели, старт микрофона, цикл транскрибации в панели."""
        import soundfile as sf
        output_dir = self.current_project_dir if self.current_project_dir else tempfile.gettempdir()
        if not hasattr(self, "_mic_streaming_stop_flag") or self._mic_streaming_stop_flag is None:
            self._mic_streaming_stop_flag = []
        self._mic_streaming_worker_done = threading.Event()
        self._mic_streaming_timer_job = [None]
        self._mic_streaming_elapsed = [0.0]
        self._mic_streaming_results = []

        def update_timer():
            if not getattr(self, "_mic_panel_visible", True):
                return
            self._mic_streaming_elapsed[0] += 1.0
            m, s = int(self._mic_streaming_elapsed[0]) // 60, int(self._mic_streaming_elapsed[0]) % 60
            try:
                self._mic_timer.configure(text=f"{m:02d}:{s:02d}")
            except Exception:
                return
            if not self._mic_streaming_stop_flag and self.mic_record.is_recording() and getattr(self, "_mic_panel_visible", True):
                try:
                    self._mic_streaming_timer_job[0] = self.after(1000, update_timer)
                except Exception:
                    pass

        def worker():
            try:
                model_size = self._settings_model_value
                device = self._device_var.get().strip().lower() or "cuda"
                if device == "auto":
                    device = "cuda"
                compute_type = self._compute_var.get().strip().lower() or "float16"
                if not self.service.load_model(model_size=model_size, device=device, compute_type=compute_type):
                    self.after(0, lambda: (
                        messagebox.showerror("Microphone", "Failed to load model."),
                        self._mic_start_btn.configure(state="normal"),
                        self._mic_stop_btn.configure(state="disabled"),
                    ))
                    return
                def safe_status(text):
                    if not getattr(self, "_mic_panel_visible", True):
                        return
                    try:
                        self._mic_status.configure(text=text)
                    except Exception:
                        pass
                self.after(0, lambda: safe_status(t("mic.recording_streaming")))
                self.mic_record.set_gain(self._mic_software_gain.get())
                err = self.mic_record.start_recording(device=self._get_mic_device_index())
                if err:
                    self.after(0, lambda e=err: (
                        messagebox.showerror("Microphone", e),
                        self._mic_start_btn.configure(state="normal"),
                        self._mic_stop_btn.configure(state="disabled"),
                    ))
                    return
                def safe_waveform_loop():
                    if not getattr(self, "_mic_panel_visible", True) or getattr(self, "_mic_streaming_stop_flag", []):
                        return
                    if self.mic_record.is_recording():
                        try:
                            self._draw_waveform()
                        except Exception:
                            pass
                        self._mic_streaming_waveform_job = self.after(80, safe_waveform_loop)
                def safe_timer_start():
                    if not getattr(self, "_mic_panel_visible", True):
                        return
                    try:
                        self._mic_streaming_timer_job[0] = self.after(1000, update_timer)
                    except Exception:
                        pass
                self.after(0, safe_timer_start)
                self.after(0, safe_waveform_loop)
                language = language_display_to_code(self._settings_language_value)
                beam_size = int(self._settings_beam_size.get()) if hasattr(self, "_settings_beam_size") else 5
                vad_filter = self._settings_vad.get() if hasattr(self, "_settings_vad") else True
                task = self._task_var.get().strip() or "transcribe"
                word_ts = self._settings_word_ts.get() if hasattr(self, "_settings_word_ts") else False
                use_glossary = self._mic_streaming_use_glossary_var.get() and bool(self.current_glossary)
                initial_prompt = GlossaryService.get_initial_prompt_text(self.current_glossary) if use_glossary else None
                interval = self._STREAMING_CHUNK_INTERVAL_SEC
                cumulative_offset = [0.0]
                while len(self._mic_streaming_stop_flag) == 0:
                    time.sleep(interval)
                    if len(self._mic_streaming_stop_flag) > 0:
                        break
                    data = self.mic_record.take_accumulated_chunks()
                    if data is None or len(data) == 0:
                        continue
                    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                    try:
                        sf.write(tmp.name, data, self.mic_record.sample_rate)
                        segs, info = self.service.transcribe(
                            tmp.name,
                            language=language,
                            initial_prompt=initial_prompt,
                            beam_size=beam_size,
                            vad_filter=vad_filter,
                            task=task,
                            word_timestamps=word_ts,
                        )
                        duration = getattr(info, "duration", 0) or 0
                        offset = cumulative_offset[0]
                        for s in (segs or []):
                            self._mic_streaming_results.append({
                                "start": s.get("start", 0) + offset,
                                "end": s.get("end", 0) + offset,
                                "text": s.get("text", ""),
                            })
                        cumulative_offset[0] += duration
                        text_bit = " ".join((s.get("text") or "").strip() for s in (segs or []))
                        if text_bit:
                            def safe_append(bit):
                                if not getattr(self, "_mic_panel_visible", True):
                                    return
                                try:
                                    self.txt_output.insert("end", bit + " ")
                                    self.txt_output.see("end")
                                except Exception:
                                    pass
                            self.after(0, lambda t=text_bit: safe_append(t))
                    finally:
                        try:
                            os.unlink(tmp.name)
                        except Exception:
                            pass
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Microphone", str(e)))
            finally:
                self._mic_streaming_worker_done.set()

        threading.Thread(target=worker, daemon=True).start()

    def _on_mic_streaming_stop(self):
        """Остановить потоковую запись и сохранить результат."""
        self._mic_streaming_stop_flag.append(True)
        self._mic_streaming_worker_done.wait(timeout=10.0)
        if getattr(self, "_mic_streaming_waveform_job", None) is not None:
            try:
                self.after_cancel(self._mic_streaming_waveform_job)
                self._mic_streaming_waveform_job = None
            except Exception:
                pass
        if self._mic_streaming_timer_job[0] is not None:
            try:
                self.after_cancel(self._mic_streaming_timer_job[0])
                self._mic_streaming_timer_job[0] = None
            except Exception:
                pass
        output_dir = self.current_project_dir if self.current_project_dir else tempfile.gettempdir()
        path, err = self.mic_record.stop_and_save(output_dir=output_dir)
        self._mic_start_btn.configure(state="normal")
        self._mic_stop_btn.configure(state="disabled")
        self._mic_streaming_elapsed[0] = 0.0
        self._mic_timer.configure(text="00:00")
        if err:
            messagebox.showerror("Microphone", err)
            return
        self.current_file = path
        self.lbl_file.configure(text=os.path.basename(path))
        self.full_results = list(getattr(self, "_mic_streaming_results", []))
        if self.current_project_dir and path:
            rel = SessionService._make_path_relative_to_project(
                path, os.path.join(self.current_project_dir, "_.wiproject")
            )
            self.file_transcripts[rel] = list(self.full_results)
            self._refresh_project_files_list()
        self._session_dirty = True
        self._show_segment_editor()
        self._rebuild_segment_list()
        self.btn_export_txt.configure(state="normal")
        self.btn_save_session.configure(state="normal")
        self.btn_ollama.configure(state="normal")

    def _start_transcription(self):
        if not self.current_file:
            messagebox.showwarning("Warning", "Please select a file first!")
            return

        model_size = self._settings_model_value
        # Блокировка интерфейса
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_browse.configure(state="disabled")
        self.btn_youtube_load.configure(state="disabled")
        self.btn_mic_record.configure(state="disabled")
        self.btn_import_youtube.configure(state="disabled")
        self.btn_export_txt.configure(state="disabled")
        self.btn_save_session.configure(state="disabled")
        self.btn_ollama.configure(state="disabled")
        
        self.txt_output.delete("1.0", "end")
        self.progress_bar.set(0)
        self.full_results = []
        self._show_streaming_output()

        # Запуск в отдельном потоке
        threading.Thread(target=self._run_logic, args=(model_size,), daemon=True).start()

    def _run_logic(self, model_size):
        try:
            device = self._device_var.get().strip().lower()
            if device == "auto":
                device = "cuda"
            compute_type = self._compute_var.get().strip().lower()
            self._update_status("Loading model... (may take some time)")
            if not self.service.load_model(model_size=model_size, device=device, compute_type=compute_type):
                self._on_complete("Error loading model.")
                return

            language = language_display_to_code(self._settings_language_value)
            beam_size = int(self._settings_beam_size.get())
            vad_filter = self._settings_vad.get()
            task = self._task_var.get().strip() or "transcribe"
            word_timestamps = self._settings_word_ts.get()

            self._update_status("Processing...")
            initial_prompt = None
            if self.current_glossary:
                initial_prompt = GlossaryService.get_initial_prompt_text(self.current_glossary)
            results, info = self.service.transcribe(
                self.current_file,
                language=language,
                initial_prompt=initial_prompt,
                beam_size=beam_size,
                vad_filter=vad_filter,
                task=task,
                word_timestamps=word_timestamps,
                progress_callback=self._on_progress
            )
            results = self._strip_tail_hallucinations(results)
            self.full_results = results
            if self.current_project_dir and self.current_file:
                rel = SessionService._make_path_relative_to_project(
                    self.current_file, os.path.join(self.current_project_dir, "_.wiproject")
                )
                self.file_transcripts[rel] = list(self.full_results)
                self.after(0, self._refresh_project_files_list)
            self._on_complete("Done!")

        except Exception as e:
            self._on_complete(f"An error occurred: {str(e)}")

    def _on_progress(self, current_time, total_duration, text):
        # Обновление UI из потока
        progress = current_time / total_duration if total_duration > 0 else 0
        self.after(0, lambda: self.progress_bar.set(progress))
        self.after(0, lambda: self.txt_output.insert("end", f"[{current_time:.1f}s] {text}\n"))
        self.after(0, lambda: self.txt_output.see("end"))

    def _update_status(self, text):
        self.after(0, lambda: self.lbl_file.configure(text=f"{os.path.basename(self.current_file)} | {text}"))

    def _on_complete(self, status_text):
        self.after(0, lambda: self.lbl_file.configure(text=f"{os.path.basename(self.current_file)} | {status_text}"))
        self.after(0, lambda: self.progress_bar.set(1.0)) # Принудительно завершаем полоску
        self.after(0, lambda: self.btn_start.configure(state="normal"))
        self.after(0, lambda: self.btn_stop.configure(state="disabled"))
        self.after(0, lambda: self.btn_browse.configure(state="normal"))
        self.after(0, lambda: self.btn_youtube_load.configure(state="normal"))
        self.after(0, lambda: self.btn_mic_record.configure(state="normal"))
        self.after(0, lambda: self.btn_import_youtube.configure(state="normal"))
        if self.full_results:
            self._session_dirty = True
            self.after(0, lambda: self.btn_export_txt.configure(state="normal"))
            self.after(0, lambda: self.btn_save_session.configure(state="normal"))
            self.after(0, lambda: self.btn_ollama.configure(state="normal"))
            self.after(0, self._show_segment_editor)
            self.after(0, self._rebuild_segment_list)

    def _show_segment_editor(self):
        """Показать редактор сегментов (список с Play-at-line), скрыть потоковый текст."""
        self.txt_output.grid_remove()
        self._segment_scroll.grid(row=0, column=0, sticky="nsew")

    def _show_streaming_output(self):
        """Показать потоковый вывод (во время транскрипции)."""
        self._segment_scroll.grid_remove()
        self.txt_output.grid(row=0, column=0, sticky="nsew")

    def _rebuild_segment_list(self):
        """Построить список сегментов: кнопка Play, таймкод, текст; при наличии suggested — подсветка и Accept/Reject."""
        for w in self._segment_scroll.winfo_children():
            w.destroy()
        if not self.full_results:
            return
        for idx, seg in enumerate(self.full_results):
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = (seg.get("text") or "").strip()
            suggested = (seg.get("suggested_text") or "").strip()
            row_f = ctk.CTkFrame(self._segment_scroll, fg_color=("gray90", "gray25"), corner_radius=4)
            row_f.grid(row=idx, column=0, sticky="ew", padx=0, pady=2)
            row_f.grid_columnconfigure(1, weight=1)
            # Play
            def _play(ix=idx):
                self._play_segment(ix)
            btn_play = ctk.CTkButton(row_f, text=t("editor.play"), width=50, command=_play)
            btn_play.grid(row=0, column=0, padx=6, pady=4, sticky="w")
            time_lbl = ctk.CTkLabel(row_f, text=f"[{start:.1f}s – {end:.1f}s]", text_color="gray", font=ctk.CTkFont(size=11))
            time_lbl.grid(row=0, column=1, padx=(0, 8), pady=4, sticky="w")
            if suggested and suggested != text:
                orig_lbl = ctk.CTkLabel(row_f, text=text, text_color="gray", anchor="w", wraplength=400)
                orig_lbl.grid(row=1, column=0, columnspan=2, padx=(56, 8), pady=(0, 2), sticky="w")
                sug_lbl = ctk.CTkLabel(row_f, text=suggested, text_color="#2d7d46", anchor="w", wraplength=400)
                sug_lbl.grid(row=2, column=0, columnspan=2, padx=(56, 8), pady=(0, 4), sticky="w")
                def _accept(ix=idx):
                    self.full_results[ix]["text"] = self.full_results[ix].pop("suggested_text", self.full_results[ix]["text"])
                    self._session_dirty = True
                    self._rebuild_segment_list()
                def _reject(ix=idx):
                    self.full_results[ix].pop("suggested_text", None)
                    self._session_dirty = True
                    self._rebuild_segment_list()
                btn_accept = ctk.CTkButton(row_f, text=t("editor.accept"), width=70, fg_color="green", hover_color="darkgreen", command=_accept)
                btn_accept.grid(row=3, column=0, padx=(56, 4), pady=(0, 4), sticky="w")
                btn_reject = ctk.CTkButton(row_f, text=t("editor.reject"), width=70, fg_color="gray", command=_reject)
                btn_reject.grid(row=3, column=1, padx=(0, 8), pady=(0, 4), sticky="w")
            else:
                text_lbl = ctk.CTkLabel(row_f, text=text or "—", anchor="w", wraplength=500)
                text_lbl.grid(row=1, column=0, columnspan=2, padx=(56, 8), pady=(0, 4), sticky="w")

    def _play_segment(self, index: int):
        """Воспроизвести сегмент по индексу (требуется current_file и audio_playback)."""
        if not self.current_file or index < 0 or index >= len(self.full_results):
            return
        if not self.audio_playback.is_available():
            messagebox.showwarning("Playback", "Install pygame to enable audio playback: pip install pygame")
            return
        seg = self.full_results[index]
        start = seg.get("start", 0)
        end = seg.get("end", 0)
        self.audio_playback.play_segment(self.current_file, start, end)

    def _stop_playback(self):
        """Остановить воспроизведение аудио."""
        self.audio_playback.stop()

    def _stop_transcription(self):
        self.service.stop()
        self._on_complete("Stopped by user")

    def _ollama_correct(self):
        if not self.full_results:
            messagebox.showwarning("Warning", "No transcript to correct. Run transcription first.")
            return
        if not self.ollama_service.is_available():
            messagebox.showerror("Ollama", "Ollama is not running or not reachable at 127.0.0.1:11434. Start Ollama and try again.")
            return
        model = self.ollama_service.get_effective_model()
        if not model:
            messagebox.showerror("Ollama", "No models found in Ollama. Run: ollama pull llama3.2 (or another model).")
            return
        system_prompt = None
        if self.current_glossary:
            system_prompt = GlossaryService.get_initial_prompt_text(self.current_glossary)
        self.btn_ollama.configure(state="disabled")
        self.btn_export_txt.configure(state="disabled")
        self.btn_save_session.configure(state="disabled")

        def run():
            try:
                total = len(self.full_results)
                def on_progress(current, tot, _):
                    progress = current / tot if tot else 0
                    self.after(0, lambda: self.progress_bar.set(progress))
                    self.after(0, lambda: self.lbl_file.configure(
                        text=f"{os.path.basename(self.current_file)} | Ollama: {current}/{tot}"
                    ))
                result = self.ollama_service.correct_segments(
                    self.full_results,
                    model=model,
                    system_prompt=system_prompt,
                    progress_callback=on_progress,
                )
                if result is not None:
                    self.after(0, lambda: self._apply_ollama_suggestions(result))
                else:
                    err = self.ollama_service.get_last_error() or "Unknown error."
                    self.after(0, lambda: messagebox.showerror("Ollama", f"Correction failed.\n\n{err}"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Ollama", str(e)))
            finally:
                self.after(0, self._ollama_done)

        threading.Thread(target=run, daemon=True).start()

    def _apply_ollama_suggestions(self, result):
        """Сохранить ответ Ollama как предложения (suggested_text); не менять принятый text до Accept."""
        for i, seg in enumerate(self.full_results):
            if i < len(result):
                self.full_results[i]["suggested_text"] = result[i].get("text", "")
        self._show_segment_editor()
        self._rebuild_segment_list()
        name = os.path.basename(self.current_file) if self.current_file else "Transcript"
        self.lbl_file.configure(text=f"{name} | Ollama done")

    def _ollama_done(self):
        self.progress_bar.set(1.0)
        self.btn_ollama.configure(state="normal")
        self.btn_export_txt.configure(state="normal")
        self.btn_save_session.configure(state="normal")

    def _export_txt(self):
        if not self.full_results or not self.current_file: return
        rows_for_export = [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in self.full_results]
        suggested_name = os.path.splitext(os.path.basename(self.current_file))[0] + ".txt"
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=suggested_name,
            filetypes=[("Text files", "*.txt")]
        )
        if file_path:
            if self.export_service.export_to_txt(rows_for_export, file_path):
                messagebox.showinfo("Success", f"File saved: {file_path}")
            else:
                messagebox.showerror("Error", "Failed to save TXT file.")

def _run_start_window():
    """Показать окно выбора: Открыть проект или Создать проект. Возвращает (open_session_path, project_dir).
    Перед destroy() отменяем все запланированные after-callback'и через Tcl, чтобы не было 'invalid command name'."""
    root = ctk.CTk()
    root.title(t("app.title"))
    root.resizable(False, False)
    w, h = 420, 200
    root.geometry(f"{w}x{h}")
    root.update_idletasks()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    x = (sw - w) // 2
    y = (sh - h) // 2
    root.geometry(f"{w}x{h}+{x}+{y}")
    choice = {"open": None, "project_dir": None}

    def on_open():
        path = filedialog.askopenfilename(
            title=t("start.open_project"),
            filetypes=[("Whisper project", "*.wiproject"), ("All files", "*.*")]
        )
        if path:
            choice["open"] = path
            root.quit()

    def on_create():
        dir_path = filedialog.askdirectory(title=t("start.create_project_choose_folder"))
        if dir_path:
            choice["project_dir"] = os.path.abspath(dir_path)
            root.quit()

    def _cleanup_and_destroy():
        try:
            ids = root.tk.eval("after info")
            for job_id in ids.split():
                try:
                    root.after_cancel(job_id)
                except Exception:
                    pass
        except Exception:
            pass
        root.destroy()

    root.grid_columnconfigure(0, weight=1)
    root.grid_rowconfigure(1, weight=1)
    lbl = ctk.CTkLabel(root, text=t("start.choose_action"), font=ctk.CTkFont(size=14))
    lbl.grid(row=0, column=0, pady=(24, 16))
    btn_frame = ctk.CTkFrame(root, fg_color="transparent")
    btn_frame.grid(row=1, column=0, pady=8)
    btn_frame.grid_columnconfigure(0, weight=1)
    btn_frame.grid_columnconfigure(1, weight=1)
    btn_open = ctk.CTkButton(btn_frame, text=t("start.open_project"), width=180, height=44, command=on_open)
    btn_open.grid(row=0, column=0, padx=12, pady=8)
    btn_create = ctk.CTkButton(btn_frame, text=t("start.create_project"), width=180, height=44, command=on_create)
    btn_create.grid(row=0, column=1, padx=12, pady=8)
    root.protocol("WM_DELETE_WINDOW", root.quit)
    root.mainloop()
    _cleanup_and_destroy()
    return choice.get("open"), choice.get("project_dir")


if __name__ == "__main__":
    saved = load_locale_preference()
    if saved:
        set_locale(saved)
    try:
        open_path, project_dir = _run_start_window()
        if open_path is None and project_dir is None:
            import sys
            sys.exit(0)
        app = App(open_session_path=open_path, project_dir=project_dir)
        app.mainloop()
    except Exception as e:
        import traceback
        with open("crash_log.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"Critical error: {e}")
