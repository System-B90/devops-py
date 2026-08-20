"""
Name: test_proc.py
Purpose: Unit tests for sb90_devops.proc.
Created: 2026-08-21
Author: Michael K. Steinberg
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from sb90_devops import proc


def test_read_pid_missing_file(tmp_path: Path) -> None:
    assert proc.read_pid(tmp_path / "nope.pid") is None


def test_read_pid_garbage(tmp_path: Path) -> None:
    pid_file = tmp_path / "dev.pid"
    pid_file.write_text("not-a-pid", encoding="utf-8")
    assert proc.read_pid(pid_file) is None


def test_read_pid_roundtrip(tmp_path: Path) -> None:
    pid_file = tmp_path / "dev.pid"
    pid_file.write_text(" 4242\n", encoding="utf-8")
    assert proc.read_pid(pid_file) == 4242


def test_pid_alive_self() -> None:
    assert proc.pid_alive(os.getpid()) is True


def test_pid_alive_dead() -> None:
    # PIDs are recycled, but this one is reserved on every platform we target:
    # 0 is the idle process on Windows and the "whole process group" sentinel
    # on POSIX, so neither reports as a live, killable process here.
    assert proc.pid_alive(999_999_999) is False


def test_run_executes_in_cwd(tmp_path: Path) -> None:
    result = proc.run(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()


def test_needs_shell_only_for_windows_npm_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    assert proc._needs_shell(["npm", "run", "dev"]) is True
    assert proc._needs_shell(["npx", "playwright", "test"]) is True
    assert proc._needs_shell(["docker", "compose", "up"]) is False
    assert proc._needs_shell([]) is False

    monkeypatch.setattr(sys, "platform", "linux")
    assert proc._needs_shell(["npm", "run", "dev"]) is False


def test_spawn_background_writes_pid_and_log(tmp_path: Path) -> None:
    log_file = tmp_path / "state" / "dev.log"
    pid_file = tmp_path / "state" / "dev.pid"
    pid = proc.spawn_background(
        [sys.executable, "-c", "print('hello from child')"],
        log_file=log_file,
        pid_file=pid_file,
        cwd=tmp_path,
    )

    assert pid > 0
    assert proc.read_pid(pid_file) == pid

    # The child is detached, so poll rather than wait() on a handle we do not own.
    deadline = time.time() + 10
    while time.time() < deadline:
        if "hello from child" in log_file.read_text(encoding="utf-8"):
            break
        time.sleep(0.1)
    assert "hello from child" in log_file.read_text(encoding="utf-8")


def test_kill_pid_unknown_pid_does_not_raise() -> None:
    proc.kill_pid(999_999_999)


def test_run_does_not_raise_by_default(tmp_path: Path) -> None:
    result = proc.run([sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path)
    assert result.returncode == 3


def test_run_check_true_raises(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        proc.run([sys.executable, "-c", "raise SystemExit(3)"], cwd=tmp_path, check=True)
