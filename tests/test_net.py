"""
Name: test_net.py
Purpose: Unit tests for sb90_devops.net.
Created: 2026-08-21
Author: Michael K. Steinberg
"""

import socket
import ssl
import urllib.error
from typing import Any

import pytest

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


class _FakeResponse:
    """Stands in for the context manager urlopen returns."""

    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


def _stub_urlopen(monkeypatch: pytest.MonkeyPatch, outcome: Any) -> list[dict]:
    """Replaces urlopen and records how it was called. No sockets, no DNS."""
    calls: list[dict] = []

    def fake_urlopen(url, timeout=None, context=None):
        calls.append({"url": url, "timeout": timeout, "context": context})
        if isinstance(outcome, Exception):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(net.urllib.request, "urlopen", fake_urlopen)
    return calls


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, (True, "200")),
        (204, (True, "204")),
        (404, (True, "404")),
        (499, (True, "499")),
        (500, (False, "500")),
        (503, (False, "503")),
    ],
)
def test_https_ok_thresholds_a_normal_response_at_500(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: tuple[bool, str]
) -> None:
    _stub_urlopen(monkeypatch, status)
    assert net.https_ok("hive.test") == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (404, (True, "404")),
        (403, (True, "403")),
        (500, (False, "500")),
        (502, (False, "502")),
    ],
)
def test_https_ok_thresholds_an_http_error_at_500(
    monkeypatch: pytest.MonkeyPatch, code: int, expected: tuple[bool, str]
) -> None:
    # urlopen raises HTTPError for 4xx/5xx rather than returning them, so this
    # branch carries the same threshold as the success path. A 404 counting as
    # "up" is the intended contract: the host answered, so it is reachable.
    error = urllib.error.HTTPError(url="https://hive.test", code=code, msg="", hdrs=None, fp=None)
    _stub_urlopen(monkeypatch, error)
    assert net.https_ok("hive.test") == expected


def test_https_ok_reports_any_other_failure_as_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_urlopen(monkeypatch, OSError("connection refused"))
    reachable, detail = net.https_ok("hive.test")
    assert reachable is False
    assert "connection refused" in detail


def test_https_ok_probes_over_https_with_verification_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_urlopen(monkeypatch, 200)

    net.https_ok("hive.test:8443")

    assert len(calls) == 1
    assert calls[0]["url"] == "https://hive.test:8443"
    assert calls[0]["timeout"] == 3
    context = calls[0]["context"]
    assert isinstance(context, ssl.SSLContext)
    # Disabling verification is the point -- dev certs are self-signed and this
    # probes liveness, not trust. Pinned so a security pass cannot silently
    # re-enable it and break every consumer's readiness check.
    assert context.check_hostname is False
    assert context.verify_mode is ssl.CERT_NONE
