"""
Name: test_net.py
Purpose: Unit tests for sb90_devops.net.
Created: 2026-08-21
Author: Michael K. Steinberg
"""

import socket

from sb90_devops import net


def test_port_in_use_true_for_bound_socket() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        assert net.port_in_use(port) is True


def test_port_in_use_false_for_closed_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    # Socket is closed; nothing is listening on the port it briefly held.
    assert net.port_in_use(port) is False


def test_https_ok_reports_failure_for_unreachable_host() -> None:
    reachable, detail = net.https_ok("no-such-host.invalid")
    assert reachable is False
    assert detail
