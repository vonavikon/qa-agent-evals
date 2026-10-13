#!/usr/bin/env python3
"""Живые тесты LLM-прокси песочницы (ТЗ финального усиления, п.4).

Поднимают scripts/sandbox-proxy.py локально с DUMMY-ключом и проверяют
весь контракт безопасности без реальных секретов и без docker (годится
для CI). Никакие настоящие ключи не используются.

Запуск: python -m unittest tests.test_proxy_live -v
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
                _req("GET", "/api/anthropic/bad")   # любой ответ = поднялся
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
        """Обход ограничения пути кодированием/нормализацией закрыт (ТЗ 4.2)."""
        for p in ("/api/anthropic/../evil", "/api/anthropic/%2e%2e/evil",
                  "/api/anthropic/%252e%252e/evil",
                  "/api/anthropic/../../etc/passwd"):
            self.assertEqual(_req("GET", p)[0], 403, p)

    def test_04_allowed_path_forwarded(self):
        """Разрешённый путь уходит к upstream (dummy-ключ => 401/403 от API,
        но НЕ 403 прокси: прокси пропустил)."""
        code, body = _req("GET", "/api/anthropic/v1/models")
        self.assertNotEqual(code, 403, body)
        self.assertNotEqual(code, 405, body)

    def test_05_body_limit(self):
        """Прокси отвечает 413 не дочитывая тело и рвёт соединение - клиент
        видит BrokenPipe. Это и есть отклонение oversized-запроса."""
        big = "x" * (5 * 1024 * 1024)
        try:
            code, _ = _req("POST", "/api/anthropic/v1/messages", body=big,
                           headers={"Content-Length": str(len(big))})
        except (BrokenPipeError, ConnectionResetError):
            return  # сервер закрыл соединение сразу после 413
        self.assertEqual(code, 413)

    def test_06_error_hides_secret(self):
        """Ошибка upstream (недостижим/отказ) не раскрывает ключ и env (ТЗ 4.2)."""
        code, body = _req("GET", "/api/anthropic/v1/models")
        self.assertNotIn("ci-dummy-key", body)
        self.assertNotIn("LLM_KEY", body)
        self.assertNotIn("Bearer", body)

    def test_07_stale_placeholder_not_forwarded_verbatim(self):
        """Клиентский Authorization (плейсхолдер) не попадает в ответ прокси."""
        code, body = _req("GET", "/api/anthropic/v1/models",
                          headers={"Authorization": "Bearer sandbox-local-placeholder"})
        self.assertNotIn("sandbox-local-placeholder", body)

    def test_08_downstream_cannot_reach_upstream_directly(self):
        """Прямой адрес upstream изнутри песочницы - это SEC-03 (docker);
        здесь проверяем обратное: прокси не сообщает клиенту адрес upstream
        при отказе (никаких внутренних деталей)."""
        code, body = _req("GET", "/api/anthropic/v1/models")
        low = body.lower()
        self.assertNotIn("api.z.ai", low)
        self.assertNotIn("upstream host", low)

    def test_09_normalize_unit(self):
        """Дублируем юнит-матрицу на живом модуле (защита от рассинхрона)."""
        for p in ("/api/anthropic", "/api/anthropic/v1/messages?x=1"):
            self.assertIsNotNone(self.mod.normalize_path(p), p)
        for p in ("/api/anthropic/../x", "/api/anthropic/%2e%2e/x"):
            self.assertIsNone(self.mod.normalize_path(p), p)


if __name__ == "__main__":
    unittest.main()
