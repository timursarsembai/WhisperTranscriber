---
name: Desktop Whisper Transcriber
overview: Создание десктопного приложения на Python для транскрибации видео/аудио с использованием faster-whisper, современным интерфейсом и автоматической упаковкой в EXE для Windows.
todos:
  - id: logic-layer
    content: Разработать TranscriptionService с поддержкой прогресс-баров и автоматической настройки DLL.
    status: completed
  - id: ui-layer
    content: Создать GUI на CustomTkinter с кнопкой Обзор и индикацией процесса.
    status: completed
  - id: export-features
    content: Реализовать экспорт результатов в TXT и PDF (с поддержкой UTF-8).
    status: completed
  - id: packaging-exe
    content: Настроить конфигурацию сборки для создания портативного EXE-файла.
    status: completed
isProject: false
---

Я предлагаю использовать современный стек на базе Python (CustomTkinter), так как это обеспечит максимальную скорость разработки через Cursor и позволит упаковать все зависимости в один EXE-файл.

### Архитектура приложения

```mermaid
graph TD
    UI["Интерфейс (CustomTkinter)"] --> Controller["Контроллер (Threading)"]
    Controller --> Logic["TranscriptionService (faster-whisper)"]
    Logic --> DLLs["CUDA/CUDNN DLLs (Автоматическая проверка)"]
    Logic --> Export["Экспорт (TXT, PDF)"]
    subgraph Packaging ["Упаковка для Windows"]
        PyInstaller["PyInstaller / Nuitka"] --> EXE["App.exe (Все включено)"]
    end
```



### Основные компоненты

1. **Ядро (TranscriptionService):**
  - Вынос логики из `test.py` в отдельный класс.
  - Автоматическая настройка путей к DLL (чтобы пользователю не нужно было ничего настраивать).
  - Механизм обратных вызовов (callbacks) для обновления прогресса в UI.
2. **Интерфейс (GUI):**
  - Выбор файла (Drag-and-Drop или кнопка Обзор).
  - Выбор модели (tiny, base, small, medium, large-v3).
  - Шкала прогресса (ProgressBar) и статусная строка.
  - Кнопки экспорта в TXT и PDF.
3. **Автономность (Portable EXE):**
  - Включение необходимых CUDA DLL в сборку.
  - Автоматическое скачивание моделей во внутренний кэш при первом запуске.

### Используемые библиотеки

- `faster-whisper` - для ИИ транскрибации.
- `customtkinter` - для современного темного интерфейса в стиле Windows 11.
- `fpdf2` - для генерации PDF с поддержкой арабского и русского языков.
- `pyinstaller` - для сборки в исполняемый файл.

