import os
import re
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas, Frame, StringVar, Toplevel, Label
from TranscriptionService import TranscriptionService


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

# Splash screen support for PyInstaller
try:
    import pyi_splash
except ImportError:
    pyi_splash = None

# Настройка внешнего вида
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(t("app.title"))
        self.geometry("800x600")

        self.service = TranscriptionService()
        self.export_service = ExportService()
        self.ollama_service = OllamaService()
        self.audio_playback = AudioPlaybackService(
            schedule_in_main_thread=lambda ms, cb: self.after(int(ms), cb)
        )
        self.full_results = []
        self.current_file = None
        self.current_session_path = None  # путь к открытому/сохранённому .wiproject
        self._session_dirty = False  # были ли изменения после последнего сохранения
        self.current_glossary_path = None
        self.current_glossary = None  # GlossaryData or None

        self._setup_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Close splash screen if it's running
        if pyi_splash:
            pyi_splash.close()

    def _setup_ui(self):
        self._tooltip_after_id = None
        self._tooltip_win = None
        self._right_panel_width = 300
        # Две колонки: [Content] [Transcription Settings | Glossary | Interface Settings — одна панель при открытии]
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(3, weight=1)

        # --- Одна строка: [Открыть] [Сохранить] | [Выбрать файл] [Старт] [Стоп] (размер кнопок прежний, иконки крупнее за счёт шрифта) ---
        _icon_font = ctk.CTkFont(size=20)
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, padx=20, pady=(10, 6), sticky="ew")
        self.top_frame.grid_columnconfigure(5, weight=1)

        self.btn_open_session = ctk.CTkButton(
            self.top_frame, text="\U0001F4C2", width=40, height=32, font=_icon_font,
            command=self._open_session,
        )
        self.btn_open_session.grid(row=0, column=0, padx=(10, 4), pady=10)

        self.btn_save_session = ctk.CTkButton(
            self.top_frame, text="\U0001F4BE", width=40, height=32, font=_icon_font,
            command=self._save_session, state="disabled",
        )
        self.btn_save_session.grid(row=0, column=1, padx=4, pady=10)

        self.btn_browse = ctk.CTkButton(
            self.top_frame, text="\U0001F4C4", width=40, height=32, font=_icon_font,
            command=self._browse_file,
        )
        self.btn_browse.grid(row=0, column=2, padx=4, pady=10)

        self.btn_start = ctk.CTkButton(
            self.top_frame, text="\u25B6", width=40, height=32, font=_icon_font,
            command=self._start_transcription, fg_color="green", hover_color="darkgreen",
        )
        self.btn_start.grid(row=0, column=3, padx=4, pady=10)

        self.btn_stop = ctk.CTkButton(
            self.top_frame, text="\u25A0", width=40, height=32, font=_icon_font,
            command=self._stop_transcription, state="disabled", fg_color="red", hover_color="darkred",
        )
        self.btn_stop.grid(row=0, column=4, padx=(4, 10), pady=10)

        self._bind_tooltip(self.btn_open_session, "session.open_project")
        self._bind_tooltip(self.btn_save_session, "session.save_project")
        self._bind_tooltip(self.btn_browse, "top.browse_file")
        self._bind_tooltip(self.btn_start, "control.start")
        self._bind_tooltip(self.btn_stop, "control.stop")

        # Строка прогресса и подпись файла под ней
        self.control_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.control_frame.grid(row=1, column=0, padx=20, pady=(0, 4), sticky="ew")
        self.control_frame.grid_columnconfigure(0, weight=1)
        self.progress_bar = ctk.CTkProgressBar(self.control_frame)
        self.progress_bar.grid(row=0, column=0, padx=0, pady=0, sticky="ew")
        self.progress_bar.set(0)

        # Под прогресс-баром — подпись с именем файла (или «Файл не выбран (форматы)»)
        self._file_status_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._file_status_frame.grid(row=2, column=0, padx=20, pady=(0, 8), sticky="ew")
        self._file_status_frame.grid_columnconfigure(0, weight=1)
        self.lbl_file = ctk.CTkLabel(self._file_status_frame, text=t("top.no_file_formats"), anchor="w")
        self.lbl_file.grid(row=0, column=0, padx=10, sticky="w")

        # Область вывода: во время транскрипции — потоковый текст; после — список сегментов с Play-at-line
        self._editor_container = ctk.CTkFrame(self, fg_color="transparent")
        self._editor_container.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="nsew")
        self._editor_container.grid_columnconfigure(0, weight=1)
        self._editor_container.grid_rowconfigure(0, weight=1)
        self.txt_output = ctk.CTkTextbox(self._editor_container, font=("Segoe UI", 12))
        self.txt_output.grid(row=0, column=0, sticky="nsew")
        self._segment_scroll = ctk.CTkScrollableFrame(self._editor_container, fg_color="transparent")
        self._segment_scroll.grid(row=0, column=0, sticky="nsew")
        self._segment_scroll.grid_columnconfigure(0, weight=1)
        self._segment_scroll.grid_remove()  # по умолчанию показываем txt_output (пустой)

        # Правая панель: своя разметка — кнопки вкладок вверху, контент сразу под ними (без CTkTabview). По умолчанию видна.
        self.settings_panel_visible = True
        self._right_panel = ctk.CTkFrame(self, width=self._right_panel_width, fg_color=("gray85", "gray20"))
        self._right_panel.grid(row=0, column=1, rowspan=5, padx=(0, 20), pady=(0, 20), sticky="nsew")
        self.grid_columnconfigure(1, minsize=self._right_panel_width)
        self._right_panel.grid_propagate(False)
        self._right_panel.grid_columnconfigure(0, weight=1)
        self._right_panel.grid_rowconfigure(1, weight=1)  # контент в row 1 растягивается
        self.geometry(f"{800 + self._right_panel_width}x600")
        self.after(100, self._force_update_scroll_regions)
        self.after(50, self._maximize_window)
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
        self.export_frame.grid(row=4, column=0, padx=20, pady=(0, 20), sticky="ew")
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

    def _ensure_panel_geometry(self, open_panel: bool):
        """Расширить или сузить окно при открытии/закрытии правой панели."""
        try:
            w, h = self.winfo_width(), self.winfo_height()
            x, y = self.winfo_x(), self.winfo_y()
        except Exception:
            w, h, x, y = 800, 600, 100, 100
        if open_panel:
            self.grid_columnconfigure(1, minsize=self._right_panel_width)
            self.geometry(f"{w + self._right_panel_width}x{h}+{x}+{y}")
        else:
            self.grid_columnconfigure(1, minsize=0)
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
            self.grid_columnconfigure(1, minsize=self._right_panel_width)
            self._right_panel.grid(row=0, column=1, rowspan=5, padx=(0, 20), pady=(0, 20), sticky="nsew")
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
            def _model_click(e, v=model_id):
                self._pick_model(v)
            for w in (row_f, name_lbl, desc_lbl):
                w.bind("<Enter>", _row_enter)
                w.bind("<Leave>", _row_leave)
                w.bind("<Button-1>", _model_click)
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
        if self.current_session_path:
            self.title(os.path.basename(self.current_session_path))
        else:
            self.title(t("app.title"))
        if not self.current_file:
            self.lbl_file.configure(text=t("top.no_file_formats"))
        self.btn_export_txt.configure(text=t("export.txt"))
        self.btn_ollama.configure(text=t("export.ollama"))
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
            self._interface_selection_label.configure(text=t("settings.selection", value=t(f"lang.{get_locale()}")))
        for code, rf in getattr(self, "_interface_row_frames", {}).items():
            rf.configure(fg_color=("#D6E4FF", "#2A4A6E") if code == get_locale() else "transparent")
            children = rf.winfo_children()
            if children:
                children[0].configure(text=t(f"lang.{code}"))

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
        self._interface_selection_label = ctk.CTkLabel(
            win, text=t("settings.selection", value=t(f"lang.{get_locale()}")),
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
        for code in ["en", "es", "ru", "kk"]:
            row_f = ctk.CTkFrame(interface_inner, fg_color="transparent", corner_radius=4, cursor="hand2")
            row_f.pack(fill="x", padx=4, pady=2)
            self._interface_row_frames[code] = row_f
            lbl = ctk.CTkLabel(row_f, text=t(f"lang.{code}"), font=ctk.CTkFont(weight="bold"), anchor="w", cursor="hand2")
            lbl.pack(fill="x")
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
            for w in (row_f, lbl):
                w.bind("<Enter>", _row_enter)
                w.bind("<Leave>", _row_leave)
                w.bind("<Button-1>", _click)
        current = get_locale()
        self._interface_selection_label.configure(text=t("settings.selection", value=t(f"lang.{current}")))
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
            path = filedialog.asksaveasfilename(
                defaultextension=".wiproject",
                initialfile=suggested,
                filetypes=[("Whisper project", "*.wiproject"), ("All files", "*.*")]
            )
        if not path:
            return False
        transcript_for_save = [
            {"start": s["start"], "end": s["end"], "text": s["text"]}
            for s in self.full_results
        ]
        session = SessionService.build_session(
            audio_path=self.current_file,
            transcript=transcript_for_save,
            model_used=self._settings_model_value,
            glossary_path=self.current_glossary_path,
        )
        if SessionService.save_session(path, session):
            self.current_session_path = path
            self._session_dirty = False
            self._update_session_title()
            messagebox.showinfo("Success", f"Session saved: {path}")
            return True
        messagebox.showerror("Error", "Failed to save session.")
        return False

    def _open_session(self):
        path = filedialog.askopenfilename(
            title="Open project session",
            filetypes=[("Whisper project", "*.wiproject"), ("All files", "*.*")]
        )
        if not path:
            return
        session = SessionService.load_session(path)
        if not session:
            messagebox.showerror("Error", "Failed to load session or invalid file.")
            return
        if not os.path.exists(session.audio_path):
            messagebox.showwarning(
                "Audio file not found",
                f"The audio file was not found:\n{session.audio_path}\n\nTranscript will be loaded, but you won't be able to re-transcribe without the file."
            )
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
        self.current_session_path = path
        self._session_dirty = False
        self._update_session_title()
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
        """Обновляет заголовок окна: имя проекта при открытом проекте, иначе — название приложения."""
        if self.current_session_path:
            self.title(os.path.basename(self.current_session_path))
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

    def _start_transcription(self):
        if not self.current_file:
            messagebox.showwarning("Warning", "Please select a file first!")
            return

        model_size = self._settings_model_value
        # Блокировка интерфейса
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_browse.configure(state="disabled")
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

if __name__ == "__main__":
    saved = load_locale_preference()
    if saved:
        set_locale(saved)
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        import traceback
        with open("crash_log.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"Critical error: {e}")
