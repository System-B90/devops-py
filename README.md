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

`run` and `spawn_background` take `cwd` explicitly rather than reading a module
global, so a consumer passes its own `ROOT`.

Windows note: `npm`/`npx` are `.cmd` shims that `CreateProcess` cannot resolve,
so both spawn helpers route *only those* through the shell. A blanket
`shell=True` re-parses every argument and breaks paths containing spaces.

## Consumers

`Bluz`, `madash` — see issue System-B90/Bluz#226.
