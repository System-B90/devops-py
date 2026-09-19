# Test-only TLS material

`localhost-test.crt` / `localhost-test.key` are a **self-signed certificate for
`CN=localhost` with a deliberately public private key**. They exist so
`tests/test_net_tls.py` can start a real HTTPS server on loopback and prove
`net.https_ok` still accepts an untrusted certificate — the property its
`CERT_NONE` setting exists for.

They secure nothing:

- The private key is committed in plaintext and readable by anyone with the repo.
- The certificate is self-signed, so no client that verifies chains will accept it
  (`test_a_verifying_client_rejects_the_same_certificate` asserts exactly that).
- It is only ever served on `127.0.0.1` on an ephemeral port, inside a test.

Never use this pair for anything else. It carries a 100-year lifetime so the
suite does not start failing on an expiry date; regenerate with:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -days 36500 \
  -keyout localhost-test.key -out localhost-test.crt \
  -subj "/CN=localhost/O=System-B90 TEST ONLY - NOT FOR PRODUCTION" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```
