# sb90-devops

Shared dev-ops helpers for System-B90 repo tooling. Each repo keeps its own
`tools.py` / `scripts/tools_impl.py` CLI; this package holds the parts that were
byte-identical across them.

## Install

```bash
pip install --extra-index-url https://system-b90.github.io/.github/pypi/ sb90-devops
```

## API

```python
from pathlib import Path

from sb90_devops import (
    https_ok,  # (host) -> (reachable, status_or_error)
    kill_pid,  # (pid) -> None
    pid_alive,  # (pid) -> bool
    port_in_use,  # (port, host="127.0.0.1") -> bool
    read_pid,  # (pid_file) -> int | None
    run,  # (cmd, cwd, **subprocess_kwargs) -> CompletedProcess
    spawn_background,  # (cmd, log_file, pid_file, cwd) -> pid
)
```

### Tokens (`sb90_devops.tokens`)

```python
from sb90_devops import find_npm_token, find_registry_token

find_npm_token()  # NPM_TOKEN, GITHUB_TOKEN, GH_TOKEN, ~/.npmrc, `gh auth token`
find_registry_token()  # CLASSIC_ACCESS_TOKEN, HIVE_REPO_TOKEN, GITHUB_TOKEN, GH_TOKEN, `gh`
```

`python -m sb90_devops.tokens docker compose build` runs a command with
`NPM_TOKEN` exported (replaces the per-repo `with-npm-token.sh`).

### Local Hive stack (`sb90_devops.hive_stack`)

Mirrors the `setup-hive` / `shared-hive-acquire` actions for local runs:

```python
from sb90_devops import hive_stack

hive_stack.check_hosts({hive_stack.HIVE_HOST: hive_stack.HIVE_HOST_IP})
stack = hive_stack.sync_stack(STATE_DIR / "pyhive-stack")  # sparse clone of pyhive
hive_stack.pull_images(stack)  # ghcr pull + retag
hive_stack.init_stack(stack, wait_attempts=90)  # up, migrate, seed
```

Failures raise `hive_stack.HiveStackError`; progress goes to the `echo`
callable (default `print`), so a typer CLI can pass `typer.echo`.

`run` and `spawn_background` take `cwd` explicitly rather than reading a module
global, so a consumer passes its own `ROOT`.

Windows note: `npm`/`npx` are `.cmd` shims that `CreateProcess` cannot resolve,
so both spawn helpers route *only those* through the shell. A blanket
`shell=True` re-parses every argument and breaks paths containing spaces.

## Consumers

`Bluz`, `madash`, `peek-a-boo` — see issue System-B90/Bluz#226.
