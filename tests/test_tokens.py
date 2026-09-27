"""
Name: test_tokens.py
Purpose: Unit tests for sb90_devops.tokens.
Created: 2026-09-28
Author: Michael K. Steinberg
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from sb90_devops import tokens

_ALL_VARS = {*tokens.NPM_TOKEN_VARS, *tokens.REGISTRY_TOKEN_VARS}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for var in _ALL_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(tokens, "gh_token", lambda: None)


def test_env_var_order_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GH_TOKEN", "gh")
    monkeypatch.setenv("NPM_TOKEN", "npm")
    assert tokens.find_npm_token() == "npm"


def test_npmrc_used_when_env_empty(tmp_path: Path) -> None:
    (tmp_path / ".npmrc").write_text(
        "@system-b90:registry=https://npm.pkg.github.com\n"
        "  //npm.pkg.github.com/:_authToken=from-npmrc  \n",
        encoding="utf-8",
    )
    assert tokens.find_npm_token() == "from-npmrc"


def test_gh_is_last_resort(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tokens, "gh_token", lambda: "from-gh")
    assert tokens.find_npm_token() == "from-gh"


def test_registry_token_skips_npmrc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".npmrc").write_text(
        "//npm.pkg.github.com/:_authToken=from-npmrc\n", encoding="utf-8"
    )
    assert tokens.find_registry_token() is None
    monkeypatch.setenv("HIVE_REPO_TOKEN", "hive")
    assert tokens.find_registry_token() == "hive"


def test_gh_token_handles_missing_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.undo()

    def boom(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(tokens.subprocess, "run", boom)
    assert tokens.gh_token() is None


def test_main_exports_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    seen: dict[str, Any] = {}

    def fake_run(args: list[str], env: dict[str, str], check: bool) -> Any:
        seen.update(args=args, token=env["NPM_TOKEN"])
        return subprocess.CompletedProcess(args, 3)

    monkeypatch.setattr(tokens.subprocess, "run", fake_run)
    assert tokens.main(["--", "docker", "compose", "build"]) == 3
    assert seen == {"args": ["docker", "compose", "build"], "token": "tok"}


def test_main_fails_without_token(capsys: pytest.CaptureFixture[str]) -> None:
    assert tokens.main(["docker"]) == 1
    assert "NPM_TOKEN" in capsys.readouterr().err


def test_main_usage() -> None:
    assert tokens.main([]) == 2
