#!/usr/bin/env python3
"""osop.exe: статика + API ленты замечаний ОСОП.

Без зависимостей, только стандартная библиотека Python 3.8+.

    python3 server.py                 # http://127.0.0.1:8080
    OSOP_PORT=9000 python3 server.py
    OSOP_HOST=0.0.0.0 python3 server.py

API:
    GET   /api/feed          список записей
    POST  /api/feed          новая запись
    PATCH /api/feed/<id>     обновить поля fix / outcome

Лента хранится в data/feed.json. При первом запуске он создаётся
из data/feed.seed.json, если такой файл есть.

Авторизации нет: держите сервер во внутренней сети или закройте
его basic auth на уровне nginx (см. README).
"""
import json
import os
import re
import secrets
import shutil
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("OSOP_DATA", ROOT / "data"))
FEED = DATA_DIR / "feed.json"
SEED = ROOT / "data" / "feed.seed.json"
HOST = os.environ.get("OSOP_HOST", "127.0.0.1")
PORT = int(os.environ.get("OSOP_PORT", "8080"))

MAX_BODY = 64 * 1024
MAX_ENTRIES = 5000
STR_LIMITS = {"date": 10, "rpd": 20, "course": 200, "expert": 120,
              "comment": 8000, "fix": 8000}
OUTCOMES = {"wait", "ok", "bad"}
TAG_RE = re.compile(r"^R\d{1,2}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
STATIC = {"/": "index.html", "/index.html": "index.html"}

lock = threading.Lock()


def load():
    if not FEED.exists():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        if SEED.exists() and SEED.resolve() != FEED.resolve():
            shutil.copyfile(SEED, FEED)
        else:
            FEED.write_text("[]", encoding="utf-8")
    return json.loads(FEED.read_text(encoding="utf-8"))


def save(items):
    tmp = FEED.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FEED)


def clean(raw, partial=False):
    """Оставляет только известные поля и обрезает их по длине."""
    if not isinstance(raw, dict):
        raise ValueError("ожидается JSON-объект")
    out = {}
    for key, limit in STR_LIMITS.items():
        if key in raw:
            out[key] = str(raw[key] or "")[:limit].strip()
    if "round" in raw:
        try:
            out["round"] = max(1, min(50, int(raw["round"])))
        except (TypeError, ValueError):
            out["round"] = 1
    if "outcome" in raw:
        if raw["outcome"] not in OUTCOMES:
            raise ValueError("outcome: wait | ok | bad")
        out["outcome"] = raw["outcome"]
    if "tags" in raw:
        tags = raw["tags"] if isinstance(raw["tags"], list) else []
        out["tags"] = [t for t in tags if isinstance(t, str) and TAG_RE.match(t)][:12]
    if "ts" in raw:
        try:
            out["ts"] = int(raw["ts"])
        except (TypeError, ValueError):
            pass
    if not partial:
        if not out.get("comment"):
            raise ValueError("нужен текст замечания (comment)")
        out.setdefault("outcome", "wait")
        out.setdefault("round", 1)
        out.setdefault("tags", [])
        out.setdefault("fix", "")
        out.setdefault("ts", int(time.time() * 1000))
    return out


class Handler(SimpleHTTPRequestHandler):
    server_version = "osop.exe"
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      ".html": "text/html; charset=utf-8"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    # --- helpers ---
    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            raise ValueError("пустое или слишком большое тело запроса")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def path_only(self):
        return self.path.split("?", 1)[0]

    # --- static: отдаём только index.html, без листинга каталога ---
    def do_GET(self):
        path = self.path_only()
        if path == "/api/feed":
            with lock:
                return self.send_json(HTTPStatus.OK, load())
        if path in STATIC:
            self.path = "/" + STATIC[path]
            return super().do_GET()
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_HEAD(self):
        if self.path_only() in STATIC:
            self.path = "/" + STATIC[self.path_only()]
            return super().do_HEAD()
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path_only() != "/api/feed":
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            doc = clean(self.read_json())
        except (ValueError, json.JSONDecodeError) as e:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        with lock:
            items = load()
            if len(items) >= MAX_ENTRIES:
                return self.send_json(HTTPStatus.INSUFFICIENT_STORAGE, {"error": "лента переполнена"})
            doc["id"] = secrets.token_hex(6)
            items.append(doc)
            save(items)
        self.send_json(HTTPStatus.CREATED, doc)

    def do_PATCH(self):
        m = re.fullmatch(r"/api/feed/([^/]+)", self.path_only())
        if not m or not ID_RE.match(m.group(1)):
            return self.send_error(HTTPStatus.NOT_FOUND)
        try:
            patch = clean(self.read_json(), partial=True)
        except (ValueError, json.JSONDecodeError) as e:
            return self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(e)})
        patch = {k: v for k, v in patch.items() if k in ("fix", "outcome")}
        with lock:
            items = load()
            for it in items:
                if it.get("id") == m.group(1):
                    it.update(patch)
                    save(items)
                    return self.send_json(HTTPStatus.OK, it)
        self.send_json(HTTPStatus.NOT_FOUND, {"error": "запись не найдена"})


if __name__ == "__main__":
    with lock:
        load()
    print(f"osop.exe: http://{HOST}:{PORT}  (данные: {FEED})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
