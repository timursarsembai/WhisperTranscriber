import os
import threading
import customtkinter as ctk
from tkinter import filedialog, messagebox
from TranscriptionService import TranscriptionService
from ExportService import ExportService

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

        self.title("Desktop Whisper Transcriber")
        self.geometry("800x600")

        self.service = TranscriptionService()
        self.export_service = ExportService()
        self.full_results = []
        self.current_file = None

        self._setup_ui()

        # Close splash screen if it's running
        if pyi_splash:
            pyi_splash.close()

    def _setup_ui(self):
        # Главный контейнер
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # Верхняя панель: выбор файла и модели
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        self.top_frame.grid_columnconfigure(1, weight=1)

        self.btn_browse = ctk.CTkButton(self.top_frame, text="Browse File", command=self._browse_file)
        self.btn_browse.grid(row=0, column=0, padx=10, pady=10)

        self.lbl_file = ctk.CTkLabel(self.top_frame, text="No file selected", anchor="w")
        self.lbl_file.grid(row=0, column=1, padx=10, pady=10, sticky="ew")

        self.lbl_model = ctk.CTkLabel(self.top_frame, text="Model:")
        self.lbl_model.grid(row=0, column=2, padx=10, pady=10)

        self.combo_model = ctk.CTkComboBox(self.top_frame, values=["tiny", "base", "small", "medium", "large-v3"])
        self.combo_model.set("base") # Base by default for speed
        self.combo_model.grid(row=0, column=3, padx=10, pady=10)

        # Control Panel (Start/Stop)
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")
        
        self.btn_start = ctk.CTkButton(self.control_frame, text="Start Transcription", command=self._start_transcription, fg_color="green", hover_color="darkgreen")
        self.btn_start.pack(side="left", padx=10, pady=10)

        self.btn_stop = ctk.CTkButton(self.control_frame, text="Stop", command=self._stop_transcription, state="disabled", fg_color="red", hover_color="darkred")
        self.btn_stop.pack(side="left", padx=10, pady=10)

        self.progress_bar = ctk.CTkProgressBar(self.control_frame)
        self.progress_bar.pack(side="left", fill="x", expand=True, padx=10, pady=10)
        self.progress_bar.set(0)

        # Область вывода текста
        self.txt_output = ctk.CTkTextbox(self, font=("Segoe UI", 12))
        self.txt_output.grid(row=2, column=0, padx=20, pady=(0, 20), sticky="nsew")

        # Bottom panel: export
        self.export_frame = ctk.CTkFrame(self)
        self.export_frame.grid(row=3, column=0, padx=20, pady=(0, 20), sticky="ew")

        self.btn_export_txt = ctk.CTkButton(self.export_frame, text="Export to TXT", command=self._export_txt, state="disabled")
        self.btn_export_txt.pack(side="left", padx=10, pady=10)

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

        model_size = self.combo_model.get()
        
        # Блокировка интерфейса
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.btn_browse.configure(state="disabled")
        self.combo_model.configure(state="disabled")
        self.btn_export_txt.configure(state="disabled")
        
        self.txt_output.delete("1.0", "end")
        self.progress_bar.set(0)
        self.full_results = []

        # Запуск в отдельном потоке
        threading.Thread(target=self._run_logic, args=(model_size,), daemon=True).start()

    def _run_logic(self, model_size):
        try:
            # 1. Load model (if needed)
            self._update_status("Loading model... (may take some time)")
            if not self.service.load_model(model_size=model_size):
                self._on_complete("Error loading model.")
                return

            # 2. Transcription
            self._update_status("Processing...")
            results, info = self.service.transcribe(
                self.current_file,
                progress_callback=self._on_progress
            )
            
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
        self.after(0, lambda: self.combo_model.configure(state="normal"))
        
        if self.full_results:
            self.after(0, lambda: self.btn_export_txt.configure(state="normal"))

    def _stop_transcription(self):
        self.service.stop()
        self._on_complete("Stopped by user")

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
