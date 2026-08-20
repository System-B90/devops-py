"""
Name: proc.py
Purpose: Subprocess spawn/lifecycle helpers shared by the per-repo dev-ops CLIs.
Created: 2026-08-21
Author: Michael K. Steinberg
"""

import os
import signal
import subprocess
import sys
from pathlib import Path

# npm/npx on Windows are .cmd shims, not .exe -- CreateProcess can't find them
# without going through the shell. Kept to this list on purpose: a blanket
# shell=True re-parses every argument, so a path with a space or an ampersand
# in it stops meaning what the caller wrote.
_WINDOWS_SHELL_SHIMS = ("npm", "npx")


def _needs_shell(cmd: list[str]) -> bool:
    return sys.platform == "win32" and bool(cmd) and cmd[0] in _WINDOWS_SHELL_SHIMS


def run(cmd: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess:
    """Runs `cmd` in `cwd`, routing Windows npm/npx shims through the shell."""
    return subprocess.run(cmd, cwd=cwd, shell=_needs_shell(cmd), **kwargs)


def spawn_background(
    cmd: list[str], log_file: Path, pid_file: Path, cwd: Path
) -> int:
    """Starts a detached background process, logs its output, and records its PID."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    with log_file.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=_needs_shell(cmd),
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
    pid_file.write_text(str(proc.pid), encoding="utf-8")
    return proc.pid


def pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def read_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
