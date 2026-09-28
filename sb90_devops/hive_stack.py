"""
Name: hive_stack.py
Purpose: Local Hive stack for dev/CI tooling: sync pyhive's hive-stack/, pull the
         published images, boot and initialize it, and check hosts-file entries.
         Mirrors the `setup-hive` / `shared-hive-acquire` actions used in CI.
Created: 2026-09-28
Author: Michael K. Steinberg
"""

import socket
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from sb90_devops.net import https_ok
from sb90_devops.tokens import find_registry_token

PYHIVE_REPO_URL = "https://github.com/System-B90/pyhive.git"
HIVE_HOST = "hive.test"
# Hive's nginx binds 127.0.0.6 (pyhive hive-stack compose; `setup-hive`'s
# `hive-host-ip` default) so it can share the host with an app's own proxy.
HIVE_HOST_IP = "127.0.0.6"
HIVE_REGISTRY_PREFIX = "ghcr.io/system-b90/hive"
ADMIN_USER = "admin"
ADMIN_PASSWORD = "Password1"
# Caps Hive's prod resource footprint, same as CI. docker-compose.yaml loads
# .env.override (optional) after .env.
_ENV_OVERRIDE = "HIVE_CORE_WORKERS=2\nHIVE_CORE_THREADS=2\nHIVE_NGINX_WORKERS=1\n"

Echo = Callable[[str], None]


class HiveStackError(RuntimeError):
    """A step failed in a way the caller should report and stop on."""


def hosts_file() -> str:
    if sys.platform == "win32":
        return r"C:\Windows\System32\drivers\etc\hosts"
    return "/etc/hosts"


def missing_hosts(wanted: Mapping[str, str]) -> list[str]:
    """`ip host` lines for each ``{host: ip}`` that does not resolve to its ip."""
    missing = []
    for host, ip in wanted.items():
        try:
            resolved = socket.gethostbyname(host)
        except socket.gaierror:
            resolved = None
        if resolved != ip:
            missing.append(f"{ip} {host}")
    return missing


def check_hosts(wanted: Mapping[str, str]) -> None:
    """Raises HiveStackError naming the hosts-file lines to add, if any."""
    missing = missing_hosts(wanted)
    if missing:
        lines = "\n".join(f"  {line}" for line in missing)
        raise HiveStackError(
            f"Missing hosts-file entries. Add to {hosts_file()} (needs admin):\n{lines}"
        )


def sync_stack(clone_dir: Path, echo: Echo = print) -> Path:
    """Sparse-clones/refreshes pyhive's hive-stack/ into ``clone_dir``."""
    if (clone_dir / ".git").exists():
        pull = subprocess.run(
            ["git", "-C", str(clone_dir), "pull", "--ff-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        if pull.returncode != 0:
            echo("warn: could not refresh pyhive hive-stack (offline?) - using cache")
    else:
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--sparse",
                PYHIVE_REPO_URL,
                str(clone_dir),
            ],
            check=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(clone_dir),
                "sparse-checkout",
                "set",
                "--no-cone",
                "hive-stack",
            ],
            check=True,
        )
    stack = clone_dir / "hive-stack"
    if not (stack / "docker-compose.yaml").exists():
        raise HiveStackError(
            "pyhive#hive-stack/docker-compose.yaml not found. "
            "Has pyhive's 'Publish Hive Images' workflow run yet?"
        )
    return stack


def compose_cmd(stack: Path, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(stack / "docker-compose.yaml"), *args]


def hive_images(compose_images: str) -> list[str]:
    """The `hive/*` image names from `docker compose config --images` output."""
    return sorted(
        {
            line.strip()
            for line in compose_images.splitlines()
            if line.strip().startswith("hive/")
        }
    )


def registry_image(image: str, sha: str) -> str:
    """ghcr name for a compose image: `hive/core:latest` -> `.../hive/core:<sha>`."""
    name = image.removeprefix("hive/").split(":")[0]
    return f"{HIVE_REGISTRY_PREFIX}/{name}:{sha}"


def pull_images(stack: Path, echo: Echo = print) -> None:
    """Pulls the published Hive images from ghcr and retags to the compose names."""
    sha = (stack / "HIVE_SHA").read_text(encoding="utf-8").strip()
    echo(f"Hive commit: {sha}")

    token = find_registry_token()
    if token:
        registry_host = HIVE_REGISTRY_PREFIX.split("/")[0]
        subprocess.run(
            ["docker", "login", registry_host, "-u", "token", "--password-stdin"],
            input=token,
            text=True,
            check=True,
        )
    else:
        echo(
            "warn: no GitHub token found (CLASSIC_ACCESS_TOKEN/HIVE_REPO_TOKEN/"
            "GITHUB_TOKEN/GH_TOKEN/gh auth) - pulls may fail if packages are private"
        )

    listing = subprocess.run(
        compose_cmd(stack, "config", "--images"),
        cwd=stack,
        capture_output=True,
        text=True,
        check=True,
    )
    images = hive_images(listing.stdout)
    if not images:
        raise HiveStackError(
            "No 'hive/*' images in docker-compose.yaml - cannot map registry images."
        )

    for img in images:
        remote = registry_image(img, sha)
        cached = subprocess.run(
            ["docker", "image", "inspect", remote], capture_output=True, check=False
        )
        if cached.returncode != 0:
            echo(f"Pulling {remote} -> {img}")
            subprocess.run(["docker", "pull", remote], check=True)
        else:
            echo(f"Cached  {remote} -> {img}")
        subprocess.run(["docker", "tag", remote, img], check=True)


def init_stack(
    stack: Path,
    wait_attempts: int = 90,
    echo: Echo = print,
    host: str = HIVE_HOST,
    interval: float = 5,
) -> None:
    """Boots + initializes the Hive stack, mirroring setup-hive registry mode."""
    (stack / ".env.override").write_text(_ENV_OVERRIDE, encoding="utf-8")

    def compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(compose_cmd(stack, *args), cwd=stack, check=check)

    compose("up", "-d")
    # `up -d` returns as soon as the containers start; `core` only waits for
    # `database` to be *started*, not accepting connections, so an immediate
    # `migrate` raced Postgres on any cold boot. Wait for the server first.
    for attempt in range(1, wait_attempts + 1):
        ready = compose("exec", "-T", "database", "pg_isready", check=False)
        if ready.returncode == 0:
            break
        echo(f"Attempt {attempt}/{wait_attempts} - Hive database not ready, waiting")
        time.sleep(interval)
    else:
        raise HiveStackError("Hive database failed to accept connections in time.")
    manage = ("core", "python", "manage.py")
    compose("exec", "-T", *manage, "migrate")
    compose("exec", "-T", *manage, "collectstatic", "--noinput")
    compose("exec", "-T", "database", "sh", "/update.sh")
    compose("exec", "-T", *manage, "service_accounts")
    compose("exec", "-T", *manage, "load_tags")
    # check=False: fails harmlessly when the superuser already exists
    # (local volumes persist across runs, unlike CI's fresh runner).
    compose(
        "exec",
        "-T",
        "-e",
        f"DJANGO_SUPERUSER_USERNAME={ADMIN_USER}",
        "-e",
        f"DJANGO_SUPERUSER_PASSWORD={ADMIN_PASSWORD}",
        "-e",
        f"DJANGO_SUPERUSER_EMAIL={ADMIN_USER}@{HIVE_HOST}",
        *manage,
        "createsuperuser",
        "--noinput",
        check=False,
    )
    compose("exec", "-T", *manage, "load_programs")

    for attempt in range(1, wait_attempts + 1):
        up, detail = https_ok(host)
        if up:
            echo(f"Hive is up (HTTP {detail})")
            return
        echo(f"Attempt {attempt}/{wait_attempts} - Hive not ready ({detail}), waiting")
        time.sleep(interval)
    raise HiveStackError("Hive failed to become ready in time.")
