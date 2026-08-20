"""
Name: net.py
Purpose: Port and HTTPS reachability probes shared by the per-repo dev-ops CLIs.
Created: 2026-08-21
Author: Michael K. Steinberg
"""

import socket
import ssl
import urllib.error
import urllib.request


def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def https_ok(host: str) -> tuple[bool, str]:
    """Returns (reachable, status-or-error). Dev certs are self-signed, so TLS
    verification is deliberately off -- this probes liveness, not trust."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(f"https://{host}", timeout=3, context=ctx) as resp:
            return resp.status < 500, str(resp.status)
    except urllib.error.HTTPError as e:
        return e.code < 500, str(e.code)
    except Exception as e:  # noqa: BLE001 - report any connection failure as down
        return False, str(e)
