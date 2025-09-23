from __future__ import annotations
import os
import re
import time
from pathlib import Path
from typing import Dict, Tuple
import requests

ALERT_BOT_TOKEN = os.getenv("ALERT_BOT_TOKEN", "8257306953:AAFBvnVVi7GNlUt9h77La_tAvuoMkZy05xQ")
ALERT_CHAT_ID = int(os.getenv("ALERT_CHAT_ID", "630043071"))

_error_regex = re.compile(r"\\b(error|exception|traceback)\\b", re.IGNORECASE)

# In-memory offsets for last read position per log file
_log_offsets: Dict[str, int] = {}


def send_telegram_alert(message: str) -> None:
    if not ALERT_BOT_TOKEN or not ALERT_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{ALERT_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": ALERT_CHAT_ID, "text": message[:4000]}, timeout=10)
    except Exception:
        pass


def scan_log_for_errors(bot_name: str, log_path: str) -> Tuple[int, int]:
    """
    Returns tuple (new_offset, matches_found)
    """
    path = Path(log_path)
    if not path.exists():
        return (_log_offsets.get(log_path, 0), 0)
    try:
        with path.open("rb") as f:
            start = _log_offsets.get(log_path, 0)
            f.seek(start)
            data = f.read()
            new_offset = start + len(data)
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
            matches = len(_error_regex.findall(text))
            if matches > 0:
                send_telegram_alert(f"[BOT ERROR] {bot_name}: найдено ошибок: {matches}\nПоследние строки:\n" + text[-800:])
            _log_offsets[log_path] = new_offset
            return new_offset, matches
    except Exception:
        return (_log_offsets.get(log_path, 0), 0)
