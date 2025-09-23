from __future__ import annotations
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import psutil
from shutil import which


def ensure_directory(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def find_entrypoint(workdir: str) -> str:
    if os.path.exists(os.path.join(workdir, "main.py")):
        return "main.py"
    if os.path.exists(os.path.join(workdir, "k.py")):
        return "k.py"
    return "main.py"


def resolve_python_executable(venv_path: Optional[str]) -> str:
    python_exe = sys.executable
    if venv_path:
        candidates = []
        if os.name == "nt":
            candidates.append(os.path.join(venv_path, "Scripts", "python.exe"))
        else:
            candidates.append(os.path.join(venv_path, "bin", "python"))
            candidates.append(os.path.join(venv_path, "bin", "python3"))
        for c in candidates:
            if os.path.exists(c):
                python_exe = c
                break
    return python_exe


def create_virtualenv(venv_path: str) -> None:
    ensure_directory(venv_path)
    # Try using current interpreter
    try:
        subprocess.check_call([sys.executable, "-m", "venv", venv_path])
    except Exception:
        # Try python3/python from PATH
        for py in ("python3", "python"):
            exe = which(py)
            if not exe:
                continue
            try:
                subprocess.check_call([exe, "-m", "venv", venv_path])
                break
            except Exception:
                continue
    # Fallback: virtualenv if available
    if not os.path.exists(os.path.join(venv_path, "Scripts" if os.name == "nt" else "bin")):
        venv_tool = which("virtualenv")
        if venv_tool:
            subprocess.check_call([venv_tool, venv_path])


def start_bot_process(workdir: str, entrypoint: str = "main.py", venv_path: Optional[str] = None, log_path: Optional[str] = None) -> int:
    ensure_directory(workdir)
    if log_path:
        ensure_directory(os.path.dirname(log_path))
    stdout_log = open(log_path or os.path.join(workdir, "logs", "bot.out.log"), "a", buffering=1, encoding="utf-8")
    stderr_log = open((log_path or os.path.join(workdir, "logs", "bot.err.log")).replace(".out.", ".err."), "a", buffering=1, encoding="utf-8")

    python_exe = resolve_python_executable(venv_path)

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
