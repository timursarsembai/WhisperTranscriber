# Desktop Whisper Transcriber

Portable application for transcribing audio and video files using AI (faster-whisper).

## Features
- Support for Russian and Arabic languages.
- Runs on GPU (CUDA) or CPU.
- No Python or library installation required (standalone EXE).
- Automatic model downloading on first run.
- **Segment editor**: after transcription, each line is a segment with **Play** (play that part of the audio). Optional: install `pygame` for playback (`pip install pygame`).
- **Ollama correction**: get AI suggestions per segment, then **Accept** or **Reject** each change.

## How to Use
1. Run `WhisperTranscriber.exe`.
2. Click **"Browse File"** and select a video or audio file.
3. Select a model (e.g., `base` for speed or `large-v3` for quality).
4. Click **"Start Transcription"**.
5. Once finished, use the **"Export to TXT"** button.

## System Requirements

Different models require different resources:

| Feature | Minimum (for tiny/base) | Recommended (for large-v3) |
| :--- | :--- | :--- |
| **CPU** | 2-core (Intel i3 / Ryzen 3) | 4-core and higher (i5 / Ryzen 5) |
| **RAM** | 4 GB | 8 GB and higher |
| **GPU** | NVIDIA with 2 GB VRAM (or CPU mode) | NVIDIA RTX with 6 GB VRAM and higher |
| **Disk Space** | ~500 MB | ~5 GB (including downloaded models) |
| **OS** | Windows 10/11 (64-bit) | Windows 10/11 (64-bit) |

**Important Note:**
For hardware acceleration (GPU mode), you must have up-to-date **NVIDIA** drivers installed. If a compatible GPU is not detected, the program will automatically switch to CPU mode, which is significantly slower.

No additional software (Python, libraries, CUDA Toolkit) needs to be installed — everything required is included in the build.

## Project Structure
- `main.py` - main interface (CustomTkinter).
- `TranscriptionService.py` - Whisper logic and DLL setup.
- `ExportService.py` - result saving logic.
- `build.py` - EXE build script.
- `models/` - folder where models will be downloaded.

## Optional: YouTube and microphone import
- **YouTube**: Paste a YouTube link and click "Load" to download audio, then transcribe as usual. Uses `yt-dlp`; FFmpeg for conversion to MP3 is provided by `imageio-ffmpeg` (no manual PATH setup). Install: `pip install yt-dlp imageio-ffmpeg` or use `requirements.txt`.
- **Microphone**: Record from the microphone, then transcribe. Requires `sounddevice` and `soundfile` (`pip install sounddevice soundfile`).

## Technical Details
- **Technologies**: Python 3.13, CustomTkinter, faster-whisper.
- **Portability**: All dependencies (including CUDA DLLs) are packed into the EXE. Models are stored in the `models` folder next to the EXE.
- **Development dependencies**: See `requirements.txt` for optional features (YouTube, mic).
