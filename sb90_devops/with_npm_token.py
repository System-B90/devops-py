"""
Name: with_npm_token.py
Purpose: `python -m sb90_devops.with_npm_token CMD...` runs CMD with NPM_TOKEN
         exported (replaces the per-repo with-npm-token.sh). A module of its own
         so `-m` does not re-execute `tokens`, which the package imports eagerly.
Created: 2026-09-28
Author: Michael K. Steinberg
"""

from sb90_devops.tokens import main

if __name__ == "__main__":
    raise SystemExit(main())
