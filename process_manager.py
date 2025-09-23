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


def _to_abs(path: str) -> str:
    return os.path.abspath(path)


def _venv_bin_dir(venv_path: str) -> str:
    return os.path.join(venv_path, "Scripts" if os.name == "nt" else "bin")


def resolve_python_executable(venv_path: Optional[str]) -> str:
    candidates = []
    if venv_path:
        if os.name == "nt":
            candidates.append(os.path.join(venv_path, "Scripts", "python.exe"))
        else:
            candidates.append(os.path.join(venv_path, "bin", "python"))
            candidates.append(os.path.join(venv_path, "bin", "python3"))
    for sys_py in (which("python3"), which("python"), sys.executable):
        if sys_py:
            candidates.append(sys_py)
    for c in candidates:
        if not c:
            continue
        c_abs = _to_abs(c)
        if os.path.exists(c_abs):
            return c_abs
    return _to_abs(sys.executable)


def create_virtualenv(venv_path: str) -> None:
    ensure_directory(venv_path)
    created = False
    errors = []
    for py_cmd in ([which("python3")] if os.name != "nt" else []) + [sys.executable, which("python")]:
        if not py_cmd:
            continue
        try:
            subprocess.check_call([py_cmd, "-m", "venv", venv_path])
            created = True
            break
        except Exception as e:
            errors.append(f"{py_cmd}: {e}")
            continue
    if not created:
        venv_tool = which("virtualenv")
        if venv_tool:
            try:
                subprocess.check_call([venv_tool, venv_path])
                created = True
            except Exception as e:
                errors.append(f"virtualenv: {e}")
    bin_dir = _venv_bin_dir(venv_path)
    if not (os.path.isdir(bin_dir) and (os.path.exists(os.path.join(bin_dir, "python")) or os.path.exists(os.path.join(bin_dir, "python3")) or os.path.exists(os.path.join(bin_dir, "python.exe")))):
        raise RuntimeError("Не удалось создать виртуальное окружение. Установите python3-venv: sudo apt install -y python3-venv. Details: " + "; ".join(errors))


def start_bot_process(workdir: str, entrypoint: str = "main.py", venv_path: Optional[str] = None, log_path: Optional[str] = None) -> int:
    ensure_directory(workdir)
    if log_path:
        ensure_directory(os.path.dirname(log_path))
    stdout_log = open(log_path or os.path.join(workdir, "logs", "bot.out.log"), "a", buffering=1, encoding="utf-8")
    stderr_log = open((log_path or os.path.join(workdir, "logs", "bot.err.log")).replace(".out.", ".err."), "a", buffering=1, encoding="utf-8")

    python_exe = resolve_python_executable(venv_path)
    if not os.path.exists(python_exe):
        # fallback to system python3
        sys_py = which("python3") or which("python") or sys.executable
        python_exe = _to_abs(sys_py)

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
