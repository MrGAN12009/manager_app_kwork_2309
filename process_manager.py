from __future__ import annotations
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil


def ensure_directory(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def find_entrypoint(workdir: str) -> str:
    if os.path.exists(os.path.join(workdir, "main.py")):
        return "main.py"
    if os.path.exists(os.path.join(workdir, "k.py")):
        return "k.py"
    return "main.py"


def start_bot_process(workdir: str, entrypoint: str = "main.py", venv_path: Optional[str] = None, log_path: Optional[str] = None) -> int:
    ensure_directory(workdir)
    if log_path:
        ensure_directory(os.path.dirname(log_path))
    stdout_log = open(log_path or os.path.join(workdir, "logs", "bot.out.log"), "a", buffering=1, encoding="utf-8")
    stderr_log = open((log_path or os.path.join(workdir, "logs", "bot.err.log")).replace(".out.", ".err."), "a", buffering=1, encoding="utf-8")

    python_exe = sys.executable
    if venv_path:
        candidate = os.path.join(venv_path, "Scripts", "python.exe") if os.name == "nt" else os.path.join(venv_path, "bin", "python")
        if os.path.exists(candidate):
            python_exe = candidate

    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

    proc = subprocess.Popen(
        [python_exe, entrypoint],
        cwd=workdir,
        stdout=stdout_log,
        stderr=stderr_log,
        env=os.environ.copy(),
        creationflags=creationflags,
    )
    return proc.pid


def stop_bot_process(pid: int) -> None:
    try:
        p = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    for child in p.children(recursive=True):
        try:
            child.terminate()
        except Exception:
            pass
    p.terminate()
    try:
        p.wait(timeout=10)
    except psutil.TimeoutExpired:
        p.kill()


def is_process_running(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
