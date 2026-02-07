import os
import re
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox, Canvas, Frame, StringVar
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
from language_names import get_language_combo_values, language_display_to_code
# UI strings: use t("key") for localized text; keys are in locales/en.json, locales/ru.json
from i18n import t, set_locale, get_locale, get_available_locales

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
        self.full_results = []
        self.current_file = None
        self.current_session_path = None  # путь к открытому/сохранённому .wiproject
        self.current_glossary_path = None
        self.current_glossary = None  # GlossaryData or None

        self._setup_ui()

        # Close splash screen if it's running
        if pyi_splash:
            pyi_splash.close()

    def _setup_ui(self):
        self._right_panel_width = 300
        # Две колонки: [Content] [Transcription Settings | Glossary | Interface Settings — одна панель при открытии]
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.grid_rowconfigure(3, weight=1)

        # --- Раздел СЕССИЯ ---
        self.session_frame = ctk.CTkFrame(self)
        self.session_frame.grid(row=0, column=0, padx=20, pady=(10, 10), sticky="ew")

        self.btn_open_session = ctk.CTkButton(self.session_frame, text=t("session.open_project"), command=self._open_session)
        self.btn_open_session.grid(row=0, column=0, padx=10, pady=10)

        self.btn_save_session = ctk.CTkButton(self.session_frame, text=t("session.save_project"), command=self._save_session, state="disabled")
        self.btn_save_session.grid(row=0, column=1, padx=10, pady=10)

        self.session_frame.grid_columnconfigure(2, weight=1)
        self.lbl_session_title = ctk.CTkLabel(
            self.session_frame, text="", anchor="w",
            font=ctk.CTkFont(weight="bold")
        )
        self.lbl_session_title.grid(row=0, column=2, padx=10, pady=10, sticky="ew")

        # --- Верхняя панель: только файл ---
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)

        self.btn_browse = ctk.CTkButton(self.top_frame, text=t("top.browse_file"), command=self._browse_file)
        self.btn_browse.grid(row=0, column=0, padx=10, pady=10)

        self.lbl_file = ctk.CTkLabel(self.top_frame, text=t("top.no_file"), anchor="w")
        self.lbl_file.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        # Control Panel (Start/Stop)
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="ew")
        
        self.btn_start = ctk.CTkButton(self.control_frame, text=t("control.start"), command=self._start_transcription, fg_color="green", hover_color="darkgreen")
        self.btn_start.pack(side="left", padx=10, pady=10)

        self.btn_stop = ctk.CTkButton(self.control_frame, text=t("control.stop"), command=self._stop_transcription, state="disabled", fg_color="red", hover_color="darkred")
        self.btn_stop.pack(side="left", padx=10, pady=10)

        self.progress_bar = ctk.CTkProgressBar(self.control_frame)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        self.progress_bar.set(0)

        # Область вывода текста
        self.txt_output = ctk.CTkTextbox(self, font=("Segoe UI", 12))
        self.txt_output.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="nsew")

        # Правая панель: своя разметка — кнопки вкладок вверху, контент сразу под ними (без CTkTabview)
        self.settings_panel_visible = False
        self._right_panel = ctk.CTkFrame(self, width=self._right_panel_width, fg_color=("gray85", "gray20"))
        self._right_panel.grid(row=0, column=1, rowspan=5, padx=(0, 20), pady=(0, 20), sticky="nsew")
        self._right_panel.grid_remove()
        self._right_panel.grid_propagate(False)
        self._right_panel.grid_columnconfigure(0, weight=1)
        self._right_panel.grid_rowconfigure(1, weight=1)  # контент в row 1 растягивается
        # Строка вкладок — сразу вверху, без отступа
        self._settings_tab_var = StringVar(value="Transcription")
        self._settings_tab_buttons = ctk.CTkSegmentedButton(
            self._right_panel,
            values=["Transcription", "Glossary", "Interface"],
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
        self.btn_settings = ctk.CTkButton(self.export_frame, text=t("bottom.settings"), command=self._toggle_settings_panel)
        self.btn_settings.grid(row=0, column=3, padx=10, pady=10)

    def _on_settings_tab_changed(self, value: str):
        """Показать выбранную вкладку настроек, остальные скрыть."""
        self._tab_transcription.grid_remove()
        self._tab_glossary.grid_remove()
        self._tab_interface.grid_remove()
        if value == "Transcription":
            self._tab_transcription.grid(row=0, column=0, sticky="nsew")
        elif value == "Glossary":
            self._tab_glossary.grid(row=0, column=0, sticky="nsew")
        else:
            self._tab_interface.grid(row=0, column=0, sticky="nsew")

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

        ctk.CTkLabel(win, text="Model", font=ctk.CTkFont(weight="bold")).grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        model_opts = [
            ("tiny", "Fastest, least accurate. Good for quick drafts."),
            ("base", "Good balance of speed and accuracy."),
            ("small", "Better accuracy, moderate speed."),
            ("medium", "High accuracy, slower."),
            ("large-v3", "Best accuracy, slowest. Requires most VRAM."),
        ]
        self._settings_model_value = "base"
        self._model_selection_label = ctk.CTkLabel(win, text=t("settings.selection", value="base"), font=ctk.CTkFont(weight="bold"), anchor="w")
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
            desc_lbl = ctk.CTkLabel(row_f, text=f"({model_desc})", font=_hint_font, text_color=_hint_color, anchor="nw", wraplength=220, justify="left", cursor="hand2")
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
        ctk.CTkLabel(win, text="Language", font=ctk.CTkFont(weight="bold")).grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        ctk.CTkLabel(win, text="Auto — auto-detect. Picking a language improves accuracy; for mixed languages (e.g. Russian + Arabic) set the main one.", font=_hint_font, text_color=_hint_color, wraplength=240, justify="left").grid(row=row, column=0, sticky="w", padx=10, pady=(0, 2))
        row += 1
        lang_opts = get_language_combo_values()
        self._settings_language_value = "Auto"
        self._lang_selection_label = ctk.CTkLabel(win, text=t("settings.selection", value="Auto"), font=ctk.CTkFont(weight="bold"), anchor="w")
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
        self._lang_buttons = {}
        for opt in lang_opts:
            def make_cmd(val):
                return lambda: self._pick_language(val)
            btn = ctk.CTkButton(_lang_inner, text=opt, width=220, anchor="w", fg_color="transparent", command=make_cmd(opt), cursor="hand2")
            btn.pack(fill="x", padx=4, pady=2)
            self._lang_buttons[opt] = btn
            btn.bind("<MouseWheel>", _scroll_lang_list_only)
            btn.bind("<Button-4>", _scroll_lang_list_only)
            btn.bind("<Button-5>", _scroll_lang_list_only)
        # подсветка выбранного языка
        self._pick_language(self._settings_language_value)
        # Явно задать scrollregion (winfo_reqheight работает даже для unmapped виджетов)
        _lang_inner.update_idletasks()
        _req_h_lang = _lang_inner.winfo_reqheight()
        _lang_canvas.configure(scrollregion=(0, 0, _lang_box_w, max(_req_h_lang, _lang_box_h + 1)))
        row += 1
        _add_hr()
        ctk.CTkLabel(win, text="Beam size", font=ctk.CTkFont(weight="bold")).grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        ctk.CTkLabel(win, text="Number of candidate sequences per step. Higher — more accurate but slower.", font=_hint_font, text_color=_hint_color, wraplength=240, justify="left").grid(row=row, column=0, sticky="w", padx=10, pady=(0, 2))
        row += 1
        beam_row = ctk.CTkFrame(win, fg_color="transparent")
        beam_row.grid(row=row, column=0, sticky="w", padx=10, pady=(0, 8))
        beam_row.grid_columnconfigure(0, weight=1)
        self._settings_beam_size = ctk.CTkSlider(beam_row, from_=1, to=10, number_of_steps=9, width=220, command=lambda v: self._beam_size_label.configure(text=str(int(v))))
        self._settings_beam_size.set(5)
        self._settings_beam_size.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._beam_size_label = ctk.CTkLabel(beam_row, text="5", width=28, font=ctk.CTkFont(weight="bold"))
        self._beam_size_label.grid(row=0, column=1, sticky="w")
        row += 1

        self._settings_vad = ctk.CTkCheckBox(win, text="VAD filter (skip silence)")
        self._settings_vad.select()
        self._settings_vad.grid(row=row, column=0, sticky="w", padx=10, pady=8)
        row += 1
        _add_hr()
        ctk.CTkLabel(win, text="Task", font=ctk.CTkFont(weight="bold")).grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        ctk.CTkLabel(win, text="Transcribe — keep original language. Translate — transcribe and translate speech to English.", font=_hint_font, text_color=_hint_color, wraplength=240, justify="left").grid(row=row, column=0, sticky="w", padx=10, pady=(0, 2))
        row += 1
        self._task_var = StringVar(value="transcribe")
        self._settings_task = ctk.CTkSegmentedButton(win, values=["transcribe", "translate"], variable=self._task_var)
        self._settings_task.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="w")
        row += 1

        self._settings_word_ts = ctk.CTkCheckBox(win, text="Word timestamps")
        self._settings_word_ts.deselect()
        self._settings_word_ts.grid(row=row, column=0, sticky="w", padx=10, pady=8)
        row += 1
        _add_hr()
        ctk.CTkLabel(win, text="Device", font=ctk.CTkFont(weight="bold")).grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        self._device_var = StringVar(value="auto")
        self._settings_device = ctk.CTkSegmentedButton(win, values=["auto", "cuda", "cpu"], variable=self._device_var)
        self._settings_device.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="w")
        row += 1
        _add_hr()
        ctk.CTkLabel(win, text="Compute type (GPU)", font=ctk.CTkFont(weight="bold")).grid(row=row, column=0, sticky="w", padx=10, pady=(10, 2))
        row += 1
        ctk.CTkLabel(win, text="GPU precision: float16 — faster, int8 — less VRAM.", font=_hint_font, text_color=_hint_color, wraplength=240, justify="left").grid(row=row, column=0, sticky="w", padx=10, pady=(0, 2))
        row += 1
        self._compute_var = StringVar(value="float16")
        self._settings_compute = ctk.CTkSegmentedButton(win, values=["float16", "int8"], variable=self._compute_var)
        self._settings_compute.grid(row=row, column=0, padx=10, pady=(0, 8), sticky="w")

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
        self.title(t("app.title"))
        self.btn_open_session.configure(text=t("session.open_project"))
        self.btn_save_session.configure(text=t("session.save_project"))
        self.btn_browse.configure(text=t("top.browse_file"))
        if not self.current_file:
            self.lbl_file.configure(text=t("top.no_file"))
        self.btn_start.configure(text=t("control.start"))
        self.btn_stop.configure(text=t("control.stop"))
        self.btn_export_txt.configure(text=t("export.txt"))
        self.btn_ollama.configure(text=t("export.ollama"))
        self.btn_settings.configure(
            text=t("bottom.hide_settings") if self.settings_panel_visible else t("bottom.settings")
        )
        if self.settings_panel_visible and hasattr(self, "_interface_title_lbl"):
            self._interface_title_lbl.configure(text=t("interface.title"))
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
        self._interface_title_lbl = ctk.CTkLabel(win, text=t("interface.title"), font=ctk.CTkFont(weight="bold"))
        self._interface_title_lbl.grid(row=row, column=0, sticky="w", padx=10, pady=(10, 8))
        row += 1
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
        """Сменить язык интерфейса и обновить надписи."""
        set_locale(code)
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

    def _pick_model(self, value):
        """Update the model selection label and highlight the selected row."""
        self._settings_model_value = value
        self._model_selection_label.configure(text=t("settings.selection", value=value))
        _sel_fg = ("#D6E4FF", "#2A4A6E")
        for mid, rf in getattr(self, "_model_row_frames", {}).items():
            rf.configure(fg_color=_sel_fg if mid == value else "transparent")

    def _pick_language(self, display_value):
        """Update the language selection label and highlight the selected button."""
        self._settings_language_value = display_value
        self._lang_selection_label.configure(text=t("settings.selection", value=display_value))
        _sel_fg = ("#D6E4FF", "#2A4A6E")
        for val, b in getattr(self, "_lang_buttons", {}).items():
            b.configure(fg_color=_sel_fg if val == display_value else "transparent")

    def _save_session(self):
        if not self.current_file or not self.full_results:
            messagebox.showwarning("Warning", "No transcription to save. Select a file and run transcription first.")
            return
        suggested = os.path.splitext(os.path.basename(self.current_file))[0] + ".wiproject"
        path = filedialog.asksaveasfilename(
            defaultextension=".wiproject",
            initialfile=suggested,
            filetypes=[("Whisper project", "*.wiproject"), ("All files", "*.*")]
        )
        if not path:
            return
        session = SessionService.build_session(
            audio_path=self.current_file,
            transcript=self.full_results,
            model_used=self._settings_model_value,
            glossary_path=self.current_glossary_path,
        )
        if SessionService.save_session(path, session):
            self.current_session_path = path
            self._update_session_title()
            messagebox.showinfo("Success", f"Session saved: {path}")
        else:
            messagebox.showerror("Error", "Failed to save session.")

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
        self.txt_output.delete("1.0", "end")
        for seg in session.transcript:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text", "")
            self.txt_output.insert("end", f"[{start:.1f}s - {end:.1f}s] {text}\n")
        self.txt_output.see("end")
        if session.transcript:
            self.btn_export_txt.configure(state="normal")
            self.btn_save_session.configure(state="normal")
            self.btn_ollama.configure(state="normal")
        self.current_session_path = path
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
            self._glossary_btn_add.configure(text="Update")

        def _clear_edit_mode():
            self._glossary_editing_original = None
            self._glossary_btn_add.configure(text="Add")
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
                ctk.CTkButton(row_f, text="Delete", width=60, command=lambda o=orig: _do_delete(o)).grid(row=0, column=1)

        def _do_delete(original: str):
            if not self.current_glossary:
                return
            self.current_glossary = GlossaryService.remove_entry(self.current_glossary, original)
            refresh_list()

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

        ctk.CTkButton(top_f, text="Open", command=do_open).grid(row=0, column=0, padx=(0, 5), pady=0)
        ctk.CTkButton(top_f, text="Save", command=do_save).grid(row=0, column=1, padx=0, pady=0)

        # Bottom: Original, Corrected, Add / Update
        self._glossary_editing_original = None
        bottom_f = ctk.CTkFrame(win, fg_color="transparent")
        bottom_f.grid(row=2, column=0, sticky="ew", padx=10, pady=10)
        bottom_f.grid_columnconfigure(1, weight=1)

        self._glossary_entry_original = ctk.CTkEntry(bottom_f)
        self._glossary_entry_corrected = ctk.CTkEntry(bottom_f)
        ctk.CTkLabel(bottom_f, text="Original:").grid(row=0, column=0, padx=(0, 5), pady=3, sticky="e")
        self._glossary_entry_original.grid(row=0, column=1, padx=0, pady=3, sticky="ew")
        ctk.CTkLabel(bottom_f, text="Corrected:").grid(row=1, column=0, padx=(0, 5), pady=3, sticky="e")
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

        self._glossary_btn_add = ctk.CTkButton(bottom_f, text="Add", command=do_add_or_update)
        self._glossary_btn_add.grid(row=2, column=1, pady=(8, 0), sticky="w")
        refresh_list()

    def _update_session_title(self):
        """Обновляет заголовок сессии в разделе Session."""
        if self.current_session_path:
            self.lbl_session_title.configure(text=os.path.basename(self.current_session_path))
        else:
            self.lbl_session_title.configure(text="")

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
            self.after(0, lambda: self.btn_export_txt.configure(state="normal"))
            self.after(0, lambda: self.btn_save_session.configure(state="normal"))
            self.after(0, lambda: self.btn_ollama.configure(state="normal"))

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
                    self.after(0, lambda: self._apply_ollama_result(result))
                else:
                    err = self.ollama_service.get_last_error() or "Unknown error."
                    self.after(0, lambda: messagebox.showerror("Ollama", f"Correction failed.\n\n{err}"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Ollama", str(e)))
            finally:
                self.after(0, self._ollama_done)

        threading.Thread(target=run, daemon=True).start()

    def _apply_ollama_result(self, result):
        self.full_results = result
        self.txt_output.delete("1.0", "end")
        for seg in result:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text", "")
            self.txt_output.insert("end", f"[{start:.1f}s - {end:.1f}s] {text}\n")
        self.txt_output.see("end")
        name = os.path.basename(self.current_file) if self.current_file else "Transcript"
        self.lbl_file.configure(text=f"{name} | Ollama done")

    def _ollama_done(self):
        self.progress_bar.set(1.0)
        self.btn_ollama.configure(state="normal")
        self.btn_export_txt.configure(state="normal")
        self.btn_save_session.configure(state="normal")

    def _export_txt(self):
        if not self.full_results or not self.current_file: return
        
        # Suggest filename based on source media file
        suggested_name = os.path.splitext(os.path.basename(self.current_file))[0] + ".txt"
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".txt", 
            initialfile=suggested_name,
            filetypes=[("Text files", "*.txt")]
        )
        if file_path:
            if self.export_service.export_to_txt(self.full_results, file_path):
                messagebox.showinfo("Success", f"File saved: {file_path}")
            else:
                messagebox.showerror("Error", "Failed to save TXT file.")

if __name__ == "__main__":
    try:
        app = App()
        app.mainloop()
    except Exception as e:
        import traceback
        with open("crash_log.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"Critical error: {e}")
