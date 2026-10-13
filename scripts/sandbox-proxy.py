#!/usr/bin/env python3
"""Реверс-прокси LLM-шлюза для песочницы (knowledge/sandbox.md, уровень docker).

Архитектура секрета (ТЗ hardening, P0-2): настоящий ключ живёт ТОЛЬКО в env
этого прокси (передаётся из приватного каталога хоста), прокси подставляет
Authorization сам. SUT получает плейсхолдер-токен - в его среде, файлах и
логах настоящего ключа нет.

Сетевая изоляция: SUT-контейнер в internal-сети, этот прокси - с двумя
интерфейсами. Наружу прокси ходит ТОЛЬКО к UPSTREAM (один хост, один
префикс пути). Из SUT доступны только пути LLM API с допустимыми методами.

Лимиты: размер тела, число запросов, таймаут апстрима - при превышении
честные 413/429/504 (обход прямым подключением невозможен: у SUT нет сети
мимо прокси; ошибка прокси НЕ открывает fallback).

Запуск: из scripts/sandbox.py (start_proxy), env: UPSTREAM, LLM_KEY.
Ответы буферизуются (вызовы короткие, десятки КБ).
"""

import collections
import http.client
import http.server
import os
import posixpath
import socketserver
import sys
import threading
import time
import urllib.parse

UPSTREAM = os.environ.get("UPSTREAM", "https://api.z.ai/api/anthropic")
LLM_KEY = os.environ.get("LLM_KEY", "")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8140"))

MAX_BODY = int(os.environ.get("MAX_BODY", str(4 * 1024 * 1024)))    # байт на запрос
MAX_RESP = int(os.environ.get("MAX_RESP", str(16 * 1024 * 1024)))   # байт на ответ
MAX_REQUESTS = int(os.environ.get("MAX_REQUESTS", "2000"))           # на запуск
MAX_RPM = int(os.environ.get("MAX_RPM", "120"))                      # запросов в минуту
MAX_CONC = int(os.environ.get("MAX_CONC", "4"))                      # одновременных
MAX_LIFETIME = int(os.environ.get("MAX_LIFETIME", "7200"))           # секунд на запуск
UPSTREAM_TIMEOUT = int(os.environ.get("UPSTREAM_TIMEOUT", "600"))    # секунд

ALLOWED_METHODS = {"GET", "POST"}
_requests = 0
_started_at = time.time()
_conc = threading.Semaphore(MAX_CONC)
_rpm = collections.deque()          # timestamps скользящего окна
_rpm_lock = threading.Lock()

u = urllib.parse.urlparse(UPSTREAM)
UP_HOST = u.hostname
UP_PORT = u.port or (443 if u.scheme == "https" else 80)
UP_PREFIX = u.path.rstrip("/")          # напр. /api/anthropic
UP_SCHEME = u.scheme

HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "te",
               "trailer", "upgrade", "proxy-authorization", "proxy-connection",
               "host", "content-length", "authorization"}


def normalize_path(raw):
    """Нормализация пути для проверки префикса (ТЗ 4.2): многократный unquote
    (закодированные %2e%2e и %252e), отсечение query/fragment, normpath.
    Решение ТОЛЬКО по нормализованному пути: ../-обходы дают путь вне
    префикса и отвергаются. None = путь запрещён."""
    p = raw.split("?", 1)[0].split("#", 1)[0]
    for _ in range(3):
        dec = urllib.parse.unquote(p)
        if dec == p:
            break
        p = dec
    norm = posixpath.normpath(p)
    if norm == UP_PREFIX or norm.startswith(UP_PREFIX + "/"):
        return norm
    return None


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # секреты в лог не пишем: только метод/путь/статус
        sys.stderr.write("[proxy] %s %s\n" % (self.command, self.path))

    def _reject(self, code, reason):
        body = reason.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self):
        global _requests
        if time.time() - _started_at > MAX_LIFETIME:
            return self._reject(503, "proxy lifetime exceeded")
        # путь: нормализация до проверки префикса - обход через %2e%2e,
        # двойное кодирование и ../ закрыты (ТЗ 4.2)
        path = normalize_path(self.path)
        if path is None:
            return self._reject(403, "only the LLM API path is allowed")
        if self.command not in ALLOWED_METHODS:
            return self._reject(405, "method not allowed")
        _requests += 1
        if _requests > MAX_REQUESTS:
            return self._reject(429, "request limit exceeded")
        with _rpm_lock:
            now = time.time()
            while _rpm and _rpm[0] < now - 60:
                _rpm.popleft()
            if len(_rpm) >= MAX_RPM:
                return self._reject(429, "rate limit exceeded")
            _rpm.append(now)
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return self._reject(413, "body too large")
        body = self.rfile.read(length) if length else None

        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_HEADERS}
        # авторизация на доверенной стороне: входящий токен (плейсхолдер)
        # выбрасывается, настоящий ключ ставит прокси
        headers["Authorization"] = "Bearer " + LLM_KEY
        headers["Host"] = UP_HOST

        if not _conc.acquire(blocking=False):
            return self._reject(429, "too many concurrent requests")
        try:
            try:
                cls = http.client.HTTPSConnection if UP_SCHEME == "https" \
                    else http.client.HTTPConnection
                conn = cls(UP_HOST, UP_PORT, timeout=UPSTREAM_TIMEOUT)
                conn.request(self.command, path, body=body, headers=headers)
                resp = conn.getresponse()
                data = resp.read(MAX_RESP + 1)
                if len(data) > MAX_RESP:
                    return self._reject(502, "upstream response too large")
            except OSError as e:
                # только тип исключения: ни секретов, ни env, ни конфигурации
                return self._reject(502, "upstream unreachable: %s" % type(e).__name__)
        finally:
            _conc.release()

        self.send_response(resp.status)
        for k, v in resp.getheaders():
            # из ответа upstream не отдаём ничего, пахнущего авторизацией
            if k.lower() not in HOP_HEADERS and "auth" not in k.lower():
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = do_HEAD = _forward


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    if not LLM_KEY or LLM_KEY == "ci-dummy-key":
        print("proxy: WARNING - LLM_KEY плейсхолдер; LLM-вызовы не "
              "авторизуются (режим sec-проверок/CI)", flush=True)
    print(f"proxy: *:{LISTEN_PORT} -> {UPSTREAM} "
          f"(limits: {MAX_BODY // 1024}KB body, {MAX_REQUESTS} req)",
          flush=True)
    Server(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
