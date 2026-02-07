---
name: Desktop Whisper Transcriber
overview: Универсальная платформа для транскрибации, редактирования и обучения на базе ИИ. Архитектура построена на едином 3-этапном конвейере (Импорт -> Обработка -> Экспорт) с поддержкой локальных LLM и системных интеграций.
todos:
  - id: core-v1
    content: Базовая транскрибация и GUI (Phase 1)
    status: completed
  - id: dictionary-storage-v2
    content: Проектирование "Умного словаря" с обучением на правках пользователя и JSON-хранилищем.
    status: pending
  - id: unified-ui-layout
    content: "Редизайн GUI под 3-этапную структуру (Вкладки/Секции: Импорт, Редактор, Постобработка)."
    status: pending
  - id: ollama-integration-smart
    content: Интеграция Ollama для коррекции текста и генерации конспектов/подзаголовков.
    status: pending
  - id: interactive-editor-player
    content: Создание редактора с функцией Play-at-line и подсветкой изменений.
    status: pending
  - id: session-management-system
    content: Реализация комплексной системы сессий (сохранение аудио+текста+правок).
    status: pending
  - id: export-ecosystem
    content: Разработка системы экспорта (Word, PDF, Anki, Obsidian).
    status: pending
isProject: true
---

### Текущий фокус: "Умный Редактор" и масштабируемая архитектура (Phase 2)

Основная задача — создать надежный фундамент для 3-этапного рабочего процесса. Мы проектируем среду, которая станет единым центром управления для импорта звука, ИИ-коррекции и генерации обучающего контента.

### Архитектура конвейера (3-Stage Pipeline)

```mermaid
graph TD
    subgraph STAGE_1 [1. IMPORT]
        Files[Файлы]
        YT[YouTube]
        Mic[Микрофон / Система]
    end

    subgraph STAGE_2 [2. PROCESSING]
        Whisper[Whisper large-v3]
        Glossary[Глоссарий правок]
        Ollama[Ollama AI-Correction]
        Editor[Smart Editor + Player]
        Whisper --> Editor
        Ollama <--> Editor
        Glossary <--> Editor
    end

    subgraph STAGE_3 [3. EXPORT]
        Formats[TXT / Word / PDF]
        Anki[Anki Cards + Audio]
        Notes[Obsidian / CRM]
    end

    STAGE_1 --> STAGE_2
    STAGE_2 --> STAGE_3
    
    Session[(Project Session .wiproject)]
    Session <--> STAGE_2
```



### Детали реализации компонентов

1. **STAGE 1: IMPORT (Data In)**
  - Подготовка модулей для захвата звука (Mic/System) и загрузки из сети (YouTube).
  - *Groundwork*: Использование абстрактного класса `AudioSource` для всех видов импорта.
2. **STAGE 2: PROCESSING (The Hub)**
  - Связка Whisper + Ollama + Интерактивный редактор.
  - *AI Learning*: Создание механизма обратной связи (правка пользователя -> обновление локального словаря).
  - *Playback*: Плеер с Waveform и функцией Play-at-line для каждой строки.
3. **STAGE 3: EXPORT (Value Out)**
  - Модуль постобработки (перевод, рерайт, Anki-карточки).
  - *Anki Work*: Автоматическое вырезание аудио-фрагмента из исходного файла для карточки.

### Менеджер сессий (Centralized State)

Файл сессии (`.wiproject`) станет "единым источником истины". Он будет хранить:

- Пути к локальным аудио-ресурсам.
- Полный транскрипт с таймлайнами и историей правок.
- Глоссарий "незнакомых слов" и пометки для экспорта.

### Используемые библиотеки (расширенный список)

- `requests` (Ollama API), `yt-dlp` (YouTube), `pyaudio` (Mic capture), `python-docx` (Word), `difflib` (Diffing).

