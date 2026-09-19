"""
Name: test_proc_lifecycle.py
Purpose: End-to-end test that spawn_background -> pid_alive -> kill_pid
         actually starts and stops a real, long-lived detached process.
Created: 2026-09-19
Author: Michael K. Steinberg
"""

import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from sb90_devops import proc

# Outlives any plausible test run, so the child is still alive when we kill it
# -- a child that exits on its own would make the assertions pass vacuously.
_SLEEP_LOOP = "import time\nwhile True: time.sleep(0.2)\n"

_WINDOWS = sys.platform == "win32"


def _wait_until(predicate, timeout: float = 30.0) -> bool:
    """Polls until `predicate` holds or the deadline passes.

    Windows teardown through taskkill is asynchronous and can take seconds on
    a loaded runner, so this polls instead of sleeping a fixed amount.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def _gone(pid: int) -> bool:
    """True once the process is really gone, reaping a zombie on the way.

    Reaping has to happen inside the poll loop, not once after `kill_pid`:
    `waitpid(WNOHANG)` returns immediately, and right after the signal is sent
    the child has usually not exited yet, so a single up-front call reaps
    nothing and the zombie survives forever.
    """
    _reap(pid)
    return not proc.pid_alive(pid)


def _reap(pid: int) -> None:
    """Clears the zombie a killed POSIX child leaves behind.

    `spawn_background` discards its Popen handle, so on POSIX the child stays
    a child of whoever called it. After SIGTERM it sits unreaped in state Z,
    and `os.kill(pid, 0)` -- what `pid_alive` uses -- still succeeds against a
    zombie. Production never sees this: the `tools.py` CLI exits right after
    spawning, the child is re-parented to init, and init reaps it. A test
    process outlives its child, so it has to reap by hand.

    Windows has no zombie state; taskkill removes the entry outright.
    """
    if _WINDOWS:
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        # Already reaped, or never our child. Either way there is nothing left.
        pass


@pytest.fixture
def spawned(tmp_path: Path) -> Iterator[tuple[int, Path]]:
    """Spawns a long-lived detached child and guarantees it is reaped."""
    pid_file = tmp_path / "state" / "dev.pid"
    pid = proc.spawn_background(
        [sys.executable, "-c", _SLEEP_LOOP],
        log_file=tmp_path / "state" / "dev.log",
        pid_file=pid_file,
        cwd=tmp_path,
    )
    try:
        yield pid, pid_file
    finally:
        # Finally-guarded: a failed assertion must not leak a detached process
        # onto a developer machine or a shared runner.
        proc.kill_pid(pid)
        _wait_until(lambda: _gone(pid), timeout=10)


def test_kill_pid_terminates_a_process_spawn_background_started(
    spawned: tuple[int, Path],
) -> None:
    pid, pid_file = spawned

    assert pid > 0
    assert proc.read_pid(pid_file) == pid
    # The child is detached, so it takes a moment to show up to tasklist on
    # Windows; poll rather than assert on the first look.
    assert _wait_until(lambda: proc.pid_alive(pid)), "child never came up"

    proc.kill_pid(pid)

    assert _wait_until(lambda: _gone(pid)), "child survived kill_pid past the deadline"
    # The pid file is the CLI's only handle on the process; it must still name
    # the pid we killed, not be cleared as a side effect.
    assert proc.read_pid(pid_file) == pid


def test_kill_pid_is_idempotent_on_an_already_dead_child(
    spawned: tuple[int, Path],
) -> None:
    pid, _ = spawned
    assert _wait_until(lambda: proc.pid_alive(pid))

    proc.kill_pid(pid)
    assert _wait_until(lambda: _gone(pid))

    # `tools.py stop` runs twice more often than anyone admits.
    proc.kill_pid(pid)
    assert proc.pid_alive(pid) is False


def test_the_spawned_child_outlives_the_call_that_started_it(
    spawned: tuple[int, Path],
) -> None:
    # spawn_background is detached by design: the CLI that starts the dev
    # server exits immediately and the server keeps running.
    pid, _ = spawned
    assert _wait_until(lambda: proc.pid_alive(pid))

    time.sleep(0.5)

    assert proc.pid_alive(pid) is True


@pytest.mark.skipif(_WINDOWS, reason="Windows has no zombie process state")
def test_pid_alive_reports_an_unreaped_zombie_as_alive(
    spawned: tuple[int, Path],
) -> None:
    """Characterization, not endorsement -- see the caveat in _reap.

    SIGTERM has landed and the process is gone, but because the caller is
    still its parent and has not reaped it, `os.kill(pid, 0)` succeeds and
    `pid_alive` says True. Any consumer that spawns and then polls in the
    *same* process (a `status` right after a `stop`) sees a stale True.
    """
    pid, _ = spawned
    assert _wait_until(lambda: proc.pid_alive(pid))

    proc.kill_pid(pid)
    # Give the signal time to land without reaping.
    assert _wait_until(
        lambda: Path(f"/proc/{pid}/stat").read_text().split()[2] == "Z",
        timeout=10,
    ), "expected the killed child to become a zombie"

    assert proc.pid_alive(pid) is True, "documents the zombie false-positive"

    _reap(pid)
    assert proc.pid_alive(pid) is False
