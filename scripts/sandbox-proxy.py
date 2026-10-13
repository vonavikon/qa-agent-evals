#!/usr/bin/env python3
"""Реверс-прокси LLM-шлюза для песочницы (knowledge/sandbox.md, уровень docker).

Схема изоляции сети: SUT-контейнер живёт в internal-сети (наружу выхода нет),
этот прокси-контейнер присоединён к internal-сети И к выходной сети. CLI
внутри песочницы ходит на http://llm:8140/api/anthropic - прокси форвардит
ЕДИНСТВЕННЫМ направлением: LLM-шлюз из env UPSTREAM. Других исходящих
направлений у SUT нет (SEC-03: любой другой хост недоступен).

Запуск (из sandbox.py): docker run python:3.12-slim -v <этот файл> -e UPSTREAM=...
Ответы апстрима буферизуются целиком (вызовы короткие, десятки КБ).
"""

import http.client
import http.server
import os
import socketserver
import sys
import urllib.parse

UPSTREAM = os.environ.get("UPSTREAM", "https://api.z.ai/api/anthropic")
LISTEN_PORT = int(os.environ.get("LISTEN_PORT", "8140"))
HOP_HEADERS = {"connection", "keep-alive", "transfer-encoding", "te",
               "trailer", "upgrade", "proxy-authorization", "proxy-connection",
               "host", "content-length"}


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[proxy] " + (fmt % args) + "\n")

    def _forward(self):
        u = urllib.parse.urlparse(UPSTREAM)
        conn_cls = http.client.HTTPSConnection if u.scheme == "https" \
            else http.client.HTTPConnection
        body = None
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            body = self.rfile.read(length)
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in HOP_HEADERS}
        try:
            conn = conn_cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=600)
            path = u.path + self.path.split("/api/anthropic", 1)[-1] \
                if self.path.startswith("/api/anthropic") or "/api/anthropic" in UPSTREAM \
                else u.path + self.path
            conn.request(self.command, path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
        except OSError as e:
            self.send_response(502)
            msg = ("upstream unreachable: %s" % e).encode()
            self.send_header("Content-Length", str(len(msg)))
            self.end_headers()
            self.wfile.write(msg)
            return
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in HOP_HEADERS:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_DELETE = do_PUT = do_PATCH = _forward


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    print(f"proxy: *:{LISTEN_PORT} -> {UPSTREAM}", flush=True)
    Server(("0.0.0.0", LISTEN_PORT), Handler).serve_forever()
