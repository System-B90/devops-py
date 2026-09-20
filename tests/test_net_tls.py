"""
Name: test_net_tls.py
Purpose: Proves https_ok accepts a self-signed certificate, against a real
         TLS server on loopback. Separate from test_net.py because this one
         binds a socket and starts a thread.
Created: 2026-09-19
Author: Michael K. Steinberg
"""

import http.server
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from sb90_devops import net

# Generated with a 100-year lifetime for CN=localhost and committed
# deliberately: regenerating per-run would need `cryptography` or an `openssl`
# binary, and the Windows runner has neither guaranteed. The key is public in
# the repo and secures nothing -- see tests/fixtures/README.md.
_FIXTURES = Path(__file__).parent / "fixtures"
_CERT = _FIXTURES / "localhost-test.crt"
_KEY = _FIXTURES / "localhost-test.key"


class _QuietHandler(http.server.BaseHTTPRequestHandler):
    # do_GET's casing is fixed by BaseHTTPRequestHandler's dispatch, not a
    # style choice. N802 is not in this repo's enabled rules, so no noqa.
    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args: object) -> None:
        """Keeps the handler from writing a request line to stderr per test."""


@pytest.fixture
def self_signed_server() -> Iterator[int]:
    """Serves HTTPS on an ephemeral loopback port with a self-signed cert."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=_CERT, keyfile=_KEY)

    # Port 0 lets the OS pick, so parallel runs and busy runners cannot collide.
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _QuietHandler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_https_ok_accepts_a_self_signed_certificate(self_signed_server: int) -> None:
    # The whole reason https_ok sets CERT_NONE. If a security pass "fixes"
    # that, every consumer's readiness probe starts failing against its own
    # dev stack -- and this is the test that would catch it.
    assert net.https_ok(f"127.0.0.1:{self_signed_server}") == (True, "200")


def test_a_verifying_client_rejects_the_same_certificate(
    self_signed_server: int,
) -> None:
    # Establishes that the certificate really is untrusted, so the test above
    # is proving https_ok's leniency rather than an accidentally valid chain.
    import urllib.error
    import urllib.request

    with pytest.raises(urllib.error.URLError) as excinfo:
        urllib.request.urlopen(
            f"https://127.0.0.1:{self_signed_server}",
            timeout=3,
            context=ssl.create_default_context(),
        )
    assert isinstance(excinfo.value.reason, ssl.SSLCertVerificationError)


def test_port_in_use_sees_the_listening_server(self_signed_server: int) -> None:
    assert net.port_in_use(self_signed_server) is True
