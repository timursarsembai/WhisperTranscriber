# -*- coding: utf-8 -*-
"""
Download audio from YouTube by URL using yt-dlp.
Returns a local file path for use with TranscriptionService and AudioPlaybackService.
"""

import os
import re
import tempfile
from typing import Callable, Optional, Tuple

try:
    import yt_dlp
    YT_DLP_AVAILABLE = True
except ImportError:
    YT_DLP_AVAILABLE = False


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes so error messages display correctly in GUI."""
    return re.sub(r"\033\[[0-9;]*m", "", str(text)).strip()


def is_youtube_url(url: str) -> bool:
    """Return True if the string looks like a YouTube URL."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    return "youtube.com" in url or "youtu.be" in url


def download_audio(
    url: str,
    output_dir: Optional[str] = None,
    progress_callback: Optional[Callable[[Optional[float], str], None]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Download audio from a YouTube (or yt-dlp supported) URL.

    Args:
        url: Video URL (e.g. https://www.youtube.com/watch?v=...).
        output_dir: Directory to save the file. If None, uses a temporary directory.
        progress_callback: Optional callback(percent_0_to_1_or_None, status_string).
            Called from the same thread as the download; run long work in another thread.

    Returns:
        (file_path, None) on success.
        (None, error_message) on failure (invalid URL, no yt-dlp, download error).
    """
    if not YT_DLP_AVAILABLE:
        return None, "yt-dlp is not installed. Install it with: pip install yt-dlp"

    url = (url or "").strip()
    if not url:
        return None, "URL is empty"

    if output_dir is None:
        output_dir = tempfile.gettempdir()
    os.makedirs(output_dir, exist_ok=True)

    # Use bundled ffmpeg from imageio-ffmpeg if available (no user PATH setup)
    ffmpeg_location = None
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            # yt-dlp accepts path to the ffmpeg executable (imageio-ffmpeg has no ffprobe; fallback still works)
            ffmpeg_location = exe
    except Exception:
        pass

    # Filename from video title (max 200 bytes, sanitized for filesystem)
    outtmpl = os.path.join(output_dir, "%(title).200B.%(ext)s")

    def progress_hook(d: dict) -> None:
        if progress_callback is None:
            return
        status = d.get("status")
        if status == "downloading":
            pct_str = d.get("_percent_str")
            if pct_str and pct_str.strip().endswith("%"):
                try:
                    pct = float(pct_str.strip().rstrip("%")) / 100.0
                    progress_callback(min(1.0, max(0.0, pct)), "downloading")
                except (ValueError, TypeError):
                    progress_callback(None, "downloading")
            else:
                progress_callback(None, "downloading")
        elif status == "finished":
            progress_callback(1.0, "finished")

    def _find_downloaded_file(ydl, info, with_postprocessor: bool) -> Optional[str]:
        requested = ydl.prepare_filename(info)
        base = os.path.splitext(requested)[0]
        exts = (".mp3", ".m4a", ".webm", ".opus", ".ogg") if with_postprocessor else (".m4a", ".webm", ".opus", ".ogg", ".mp3")
        for ext in exts:
            path = base + ext
            if os.path.isfile(path):
                return os.path.abspath(path)
        if os.path.isfile(requested):
            return os.path.abspath(requested)
        return None

    # 1) Try with FFmpeg postprocessor (mp3) for best compatibility
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "restrict_filenames": True,
        "quiet": True,
        "no_warnings": True,
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ],
        "progress_hooks": [progress_hook],
    }
    if ffmpeg_location:
        ydl_opts["ffmpeg_location"] = ffmpeg_location
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                return None, "Could not get video info"
            path = _find_downloaded_file(ydl, info, with_postprocessor=True)
            if path:
                return path, None
            return None, "Downloaded file not found"
    except yt_dlp.utils.DownloadError as e:
        err_text = _strip_ansi(str(e) or "")
        if "ffmpeg" in err_text.lower() or "ffprobe" in err_text.lower():
            # 2) FFmpeg not installed — download without conversion (m4a/webm etc.)
            ydl_opts_no_ff = {
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "restrict_filenames": True,
                "quiet": True,
                "no_warnings": True,
                "progress_hooks": [progress_hook],
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts_no_ff) as ydl:
                    info = ydl.extract_info(url, download=True)
                    if not info:
                        return None, "Could not get video info"
                    path = _find_downloaded_file(ydl, info, with_postprocessor=False)
                    if path:
                        return path, None
                    return None, "Downloaded file not found"
            except Exception as e2:
                return None, _strip_ansi(str(e2) or "Download error")
        return None, err_text or "Download error"
    except Exception as e:
        return None, _strip_ansi(str(e) or "Unknown error")
