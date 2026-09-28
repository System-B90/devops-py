"""
Name: test_hive_stack.py
Purpose: Unit tests for sb90_devops.hive_stack (no docker/git needed).
Created: 2026-09-28
Author: Michael K. Steinberg
"""

import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest

from sb90_devops import hive_stack


def test_missing_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    table = {"hive.test": "127.0.0.6", "app.dev": "127.0.0.1"}

    def resolve(host: str) -> str:
        if host in table:
            return table[host]
        raise socket.gaierror(host)

    monkeypatch.setattr(hive_stack.socket, "gethostbyname", resolve)
    wanted = {"hive.test": "127.0.0.6", "app.dev": "127.0.0.3", "x.dev": "127.0.0.9"}
    assert hive_stack.missing_hosts(wanted) == ["127.0.0.3 app.dev", "127.0.0.9 x.dev"]
    with pytest.raises(hive_stack.HiveStackError, match="127.0.0.3 app.dev"):
        hive_stack.check_hosts(wanted)
    hive_stack.check_hosts({"hive.test": "127.0.0.6"})


def test_hive_images_and_registry_names() -> None:
    listing = "hive/core:latest\npostgres:16\n  hive/nginx\nhive/core:latest\n"
    assert hive_stack.hive_images(listing) == ["hive/core:latest", "hive/nginx"]
    assert (
        hive_stack.registry_image("hive/core:latest", "abc")
        == "ghcr.io/system-b90/hive/core:abc"
    )


def test_sync_stack_requires_compose_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    monkeypatch.setattr(
        hive_stack.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", ""),
    )
    warnings: list[str] = []
    with pytest.raises(hive_stack.HiveStackError, match="docker-compose.yaml"):
        hive_stack.sync_stack(clone, echo=warnings.append)
    assert warnings and "cache" in warnings[0]

    (clone / "hive-stack").mkdir()
    (clone / "hive-stack" / "docker-compose.yaml").write_text("", encoding="utf-8")
    assert hive_stack.sync_stack(clone, echo=warnings.append) == clone / "hive-stack"


def test_init_stack_runs_setup_sequence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **_kwargs: Any) -> subprocess.CompletedProcess:
        calls.append(cmd[4:])  # drop `docker compose -f <file>`
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(hive_stack.subprocess, "run", fake_run)
    monkeypatch.setattr(hive_stack, "https_ok", lambda host: (True, "200"))
    hive_stack.init_stack(tmp_path, wait_attempts=1, echo=lambda _m: None)

    assert (
        (tmp_path / ".env.override")
        .read_text(encoding="utf-8")
        .startswith("HIVE_CORE_WORKERS=2")
    )
    assert calls[0] == ["up", "-d"]
    assert calls[1][-1] == "pg_isready"
    steps = [c[-1] for c in calls[2:]]
    assert steps == [
        "migrate",
        "--noinput",
        "/update.sh",
        "service_accounts",
        "load_tags",
        "--noinput",
        "load_programs",
    ]


def test_init_stack_times_out(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        hive_stack.subprocess,
        "run",
        lambda cmd, **k: subprocess.CompletedProcess(cmd, 1),
    )
    with pytest.raises(hive_stack.HiveStackError, match="database"):
        hive_stack.init_stack(tmp_path, wait_attempts=2, echo=print, interval=0)
