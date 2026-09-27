"""
Name: tokens.py
Purpose: One GitHub token lookup for GitHub Packages (npm) and ghcr.io pulls,
         replacing the per-repo copies (env vars, ~/.npmrc, `gh auth token`).
Created: 2026-09-28
Author: Michael K. Steinberg
"""

import os
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

NPM_TOKEN_VARS = ("NPM_TOKEN", "GITHUB_TOKEN", "GH_TOKEN")
REGISTRY_TOKEN_VARS = (
    "CLASSIC_ACCESS_TOKEN",
    "HIVE_REPO_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
)
_NPMRC_PREFIX = "//npm.pkg.github.com/:_authToken="


def npmrc_token(npmrc: Path | None = None) -> str | None:
    """The GitHub Packages token from ~/.npmrc (or ``npmrc``), if any."""
    path = npmrc if npmrc is not None else Path.home() / ".npmrc"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(_NPMRC_PREFIX):
            return line.split("=", 1)[1].strip() or None
    return None


def gh_token() -> str | None:
    """`gh auth token`, or None when the GitHub CLI is missing or logged out."""
    try:
        gh = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    token = gh.stdout.strip()
    return token if gh.returncode == 0 and token else None


def find_token(
    env_vars: Iterable[str] = NPM_TOKEN_VARS,
    *,
    npmrc: bool = True,
    gh: bool = True,
) -> str | None:
    """First token found in ``env_vars`` (in order), then ~/.npmrc, then `gh`."""
    for var in env_vars:
        token = os.environ.get(var)
        if token:
            return token
    if npmrc:
        token = npmrc_token()
        if token:
            return token
    return gh_token() if gh else None


def find_npm_token() -> str | None:
    """Token for pulling @system-b90/* from GitHub Packages."""
    return find_token(NPM_TOKEN_VARS)


def find_registry_token() -> str | None:
    """Token for ghcr.io pulls, same fallback order as CI's secrets."""
    return find_token(REGISTRY_TOKEN_VARS, npmrc=False)


def main(argv: Sequence[str] | None = None) -> int:
    """Runs CMD with NPM_TOKEN exported; see `python -m sb90_devops.with_npm_token`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("usage: python -m sb90_devops.with_npm_token CMD...", file=sys.stderr)
        return 2
    token = find_npm_token()
    if not token:
        print(
            "[ERROR] No GitHub Packages token: set NPM_TOKEN, add it to ~/.npmrc,"
            " or run: gh auth login (then: gh auth refresh -s read:packages)",
            file=sys.stderr,
        )
        return 1
    env = {**os.environ, "NPM_TOKEN": token}
    try:
        return subprocess.run(args, env=env, check=False).returncode
    except OSError as error:
        print(f"[ERROR] Could not run {args[0]}: {error}", file=sys.stderr)
        return 127
