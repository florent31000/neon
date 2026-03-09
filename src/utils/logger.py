"""
Logger for Neon.
Thread-safe logging with callback support for UI display.
"""

import threading
from datetime import datetime
from typing import Callable, List, Optional


_lock = threading.Lock()
_log_lines: List[str] = []
_log_callback: Optional[Callable[[str, str], None]] = None
MAX_LOG_LINES = 500


def set_log_callback(callback: Optional[Callable[[str, str], None]]):
    global _log_callback
    _log_callback = callback


def log(message: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{timestamp}] [{level}] {message}"

    with _lock:
        _log_lines.append(line)
        if len(_log_lines) > MAX_LOG_LINES:
            del _log_lines[: len(_log_lines) - MAX_LOG_LINES]

    print(line)

    cb = _log_callback
    if cb:
        try:
            cb(message, level)
        except Exception:
            pass


def get_all_logs() -> str:
    with _lock:
        return "\n".join(_log_lines)
