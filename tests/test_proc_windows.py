"""
Name: test_proc_windows.py
Purpose: Drives the win32 branches of sb90_devops.proc with a patched
         sys.platform. Redundant with the windows-latest CI leg by design:
         these keep the branches covered if the matrix ever collapses back
         to a Linux-only self-hosted pool. The one test here that needs a
         real Windows kernel is skipped elsewhere.
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


def test_needs_shell_matches_only_exact_lowercase_shims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Characterization of _needs_shell's limits, so they stay deliberate.

    The match is an exact, case-sensitive membership test on cmd[0]. Every
    case below therefore falls through to shell=False. That is fine for the
    callers this package has -- they all spell it plain `npm` -- but it is a
    sharp edge worth being visible rather than rediscovered.
    """
    monkeypatch.setattr(sys, "platform", "win32")

    assert proc._needs_shell([]) is False

    # Windows paths are case-insensitive; this membership test is not.
    assert proc._needs_shell(["NPM", "run", "dev"]) is False
    assert proc._needs_shell(["Npm", "run", "dev"]) is False

    # Naming the shim explicitly is the obvious workaround for a shell-routing
    # bug, and it silently turns routing off instead.
    assert proc._needs_shell(["npm.cmd", "run", "dev"]) is False

    # An absolute path needs no shell resolution, so falling through is right
    # here -- but it is the same code path as the cases above, not a decision.
    assert proc._needs_shell([r"C:\Program Files\nodejs\npm.cmd", "run"]) is False

    # Extra arguments never matter; only cmd[0] is inspected.
    assert proc._needs_shell(["npm"]) is True


@pytest.mark.skipif(sys.platform != "win32", reason="exercises real CreateProcess/cmd.exe routing")
def test_run_launches_a_real_cmd_shim_through_the_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason this module exists, executed rather than asserted about.

    A .cmd file cannot be launched by CreateProcess directly, so this fails
    with FileNotFoundError the moment shell routing regresses -- the failure
    mode that would otherwise take down every consumer repo's dev-server
    workflow while the whole suite stayed green.

    Uses a stand-in shim so the runner needs no Node installation.
    """
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    (shim_dir / "npm.cmd").write_text("@echo off\r\necho shim-ran %*\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")

    result = proc.run(["npm", "run", "dev"], cwd=tmp_path, capture_output=True, text=True)

    assert result.returncode == 0
    assert "shim-ran" in result.stdout
    # Arguments survive the extra round of shell parsing.
    assert "run dev" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="exercises real CreateProcess/cmd.exe routing")
def test_spawn_background_launches_a_real_cmd_shim_through_the_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same routing, through the detached-spawn path the dev server uses."""
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    (shim_dir / "npm.cmd").write_text("@echo off\r\necho shim-ran %*\r\n", encoding="utf-8")
    monkeypatch.setenv("PATH", f"{shim_dir}{os.pathsep}{os.environ['PATH']}")

    log_file = tmp_path / "state" / "dev.log"
    pid = proc.spawn_background(
        ["npm", "run", "dev"],
        log_file=log_file,
        pid_file=tmp_path / "state" / "dev.pid",
        cwd=tmp_path,
    )

    assert pid > 0
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if "shim-ran" in log_file.read_text(encoding="utf-8"):
            break
        time.sleep(0.05)
    assert "shim-ran" in log_file.read_text(encoding="utf-8")
