#!/usr/bin/env python3
"""Live tests of the sandbox LLM proxy (final hardening spec, item 4).

They start scripts/sandbox-proxy.py locally with a DUMMY key and check the
whole security contract without real secrets and without docker (fits CI).
No real keys are used.

Run: python -m unittest tests.test_proxy_live -v
"""

import http.client
import importlib.util
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROXY = os.path.join(ROOT, "scripts", "sandbox-proxy.py")
PORT = 18140


def _load():
    os.environ["UPSTREAM"] = "https://api.z.ai/api/anthropic"
    os.environ["LLM_KEY"] = "ci-dummy-key"
    os.environ["LISTEN_PORT"] = str(PORT)
    spec = importlib.util.spec_from_file_location("sp_live", PROXY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _req(method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=15)
    conn.request(method, path, body=body, headers=headers or {})
    r = conn.getresponse()
    data = r.read()
    conn.close()
    return r.status, data.decode("utf-8", "replace")


class ProxyLive(unittest.TestCase):
    proc = None
    mod = None

    @classmethod
    def setUpClass(cls):
        cls.mod = _load()
        cls.proc = subprocess.Popen(
            [sys.executable, PROXY],
            env=dict(os.environ, LISTEN_PORT=str(PORT),
                     LLM_KEY="ci-dummy-key",
                     UPSTREAM="https://api.z.ai/api/anthropic"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            try:
                _req("GET", "/api/anthropic/bad")   # any response = it is up
                return
            except OSError:
                time.sleep(0.25)
        raise RuntimeError("прокси не поднялся")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(timeout=10)

    def test_01_method_denied(self):
        code, _ = _req("DELETE", "/api/anthropic/v1/x")
        self.assertEqual(code, 405)

    def test_02_foreign_path_denied(self):
        for p in ("/other", "/", "//api.z.ai/x", "/api/anthropi"):
            self.assertEqual(_req("GET", p)[0], 403, p)

    def test_03_path_traversal_denied(self):
        """Bypassing the path restriction via encoding/normalization is closed (spec 4.2)."""
        for p in ("/api/anthropic/../evil", "/api/anthropic/%2e%2e/evil",
                  "/api/anthropic/%252e%252e/evil",
                  "/api/anthropic/../../etc/passwd"):
            self.assertEqual(_req("GET", p)[0], 403, p)

    def test_04_allowed_path_forwarded(self):
        """An allowed path goes to upstream (a dummy key => 401/403 from the
        API, but NOT a proxy 403: the proxy let it through)."""
        code, body = _req("GET", "/api/anthropic/v1/models")
        self.assertNotEqual(code, 403, body)
        self.assertNotEqual(code, 405, body)

    def test_05_body_limit(self):
        """The proxy answers 413 without reading the body and drops the
        connection - the client sees BrokenPipe. That is exactly the
        oversized-request rejection."""
        big = "x" * (5 * 1024 * 1024)
        try:
            code, _ = _req("POST", "/api/anthropic/v1/messages", body=big,
                           headers={"Content-Length": str(len(big))})
        except (BrokenPipeError, ConnectionResetError):
            return  # the server closed the connection right after the 413
        self.assertEqual(code, 413)

    def test_06_error_hides_secret(self):
        """An upstream error (unreachable/refused) does not disclose the key or env (spec 4.2)."""
        code, body = _req("GET", "/api/anthropic/v1/models")
        self.assertNotIn("ci-dummy-key", body)
        self.assertNotIn("LLM_KEY", body)
        self.assertNotIn("Bearer", body)

    def test_07_stale_placeholder_not_forwarded_verbatim(self):
        """The client's Authorization (a placeholder) does not appear in the proxy's response."""
        code, body = _req("GET", "/api/anthropic/v1/models",
                          headers={"Authorization": "Bearer sandbox-local-placeholder"})
        self.assertNotIn("sandbox-local-placeholder", body)

    def test_08_downstream_cannot_reach_upstream_directly(self):
        """Reaching the upstream address directly from inside the sandbox is
        SEC-03 (docker); here we check the reverse: the proxy does not tell
        the client the upstream address on refusal (no internal details)."""
        code, body = _req("GET", "/api/anthropic/v1/models")
        low = body.lower()
        self.assertNotIn("api.z.ai", low)
        self.assertNotIn("upstream host", low)

    def test_09_normalize_unit(self):
        """Duplicate the unit matrix on the live module (protection against desync)."""
        for p in ("/api/anthropic", "/api/anthropic/v1/messages?x=1"):
            self.assertIsNotNone(self.mod.normalize_path(p), p)
        for p in ("/api/anthropic/../x", "/api/anthropic/%2e%2e/x"):
            self.assertIsNone(self.mod.normalize_path(p), p)


if __name__ == "__main__":
    unittest.main()
