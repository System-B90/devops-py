"""
Name: test_proc_windows.py
Purpose: Drives the win32 branches of sb90_devops.proc with a patched
         sys.platform. CI runs on a Linux-only self-hosted pool, so these
         branches get no real execution anywhere else.
Created: 2026-08-21
Author: Michael K. Steinberg
"""

import subprocess
import sys
from pathlib import Path

import pytest

from sb90_devops import proc


class _FakeCompleted:
    def __init__(self, stdout: str = "") -> None:
        self.stdout = stdout
        self.returncode = 0


@pytest.fixture
def as_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    # DETACHED_PROCESS and CREATE_NEW_PROCESS_GROUP only exist on Windows
    # builds of the stdlib, so spawn_background's flag lookup has to be
    # satisfied before the branch can be driven from Linux.
    for flag in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS"):
        if not hasattr(subprocess, flag):
            monkeypatch.setattr(subprocess, flag, 0, raising=False)


def test_pid_alive_parses_tasklist(as_windows, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompleted(stdout="python.exe   4242 Console   1   12,345 K")

    monkeypatch.setattr(proc.subprocess, "run", fake_run)

    assert proc.pid_alive(4242) is True
    assert proc.pid_alive(9999) is False
    assert calls[0] == ["tasklist", "/FI", "PID eq 4242"]


def test_kill_pid_uses_taskkill_tree(as_windows, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _FakeCompleted()

    monkeypatch.setattr(proc.subprocess, "run", fake_run)
    proc.kill_pid(4242)

    # /T matters: the dev server spawns child processes, and killing only the
    # parent leaves the port bound.
    assert calls == [["taskkill", "/PID", "4242", "/T", "/F"]]


def test_run_shells_only_npm_shims(as_windows, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict] = []

    def fake_run(cmd, **kwargs):
        seen.append({"cmd": cmd, **kwargs})
        return _FakeCompleted()

    monkeypatch.setattr(proc.subprocess, "run", fake_run)

    proc.run(["npm", "run", "dev"], cwd=Path("."))
    proc.run(["docker", "compose", "up"], cwd=Path("."))

    assert seen[0]["shell"] is True
    assert seen[1]["shell"] is False


def test_spawn_background_sets_detached_flags(
    as_windows, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: dict = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            seen.update(cmd=cmd, **kwargs)
            self.pid = 4242

    monkeypatch.setattr(proc.subprocess, "Popen", FakePopen)

    pid = proc.spawn_background(
        ["npm", "run", "dev"],
        log_file=tmp_path / "dev.log",
        pid_file=tmp_path / "dev.pid",
        cwd=tmp_path,
    )

    assert pid == 4242
    expected = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    assert seen["creationflags"] == expected
    assert seen["shell"] is True
    assert (tmp_path / "dev.pid").read_text(encoding="utf-8") == "4242"
