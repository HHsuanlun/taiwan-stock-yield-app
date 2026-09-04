"""Zero-dependency local server for previewing the valuation MVP."""

from __future__ import annotations

import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from backend.data.providers import FixtureProvider
from backend.valuation.valuation_engine import calculate

ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"
PROVIDER = FixtureProvider()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND), **kwargs)

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.path = "/index.html"
            return super().do_GET()
        if path.startswith("/static/"):
            self.path = path.removeprefix("/static")
            return super().do_GET()
        if path == "/api/stocks/2881/snapshot":
            return self.send_json(PROVIDER.get_snapshot("2881"))
        if path == "/api/stocks/2881/history":
            return self.send_json(PROVIDER.get_history("2881"))
        if path == "/api/stocks/2881/valuation":
            return self.send_json(self.valuation({}))
        if path.startswith("/api/"):
            return self.send_json({"detail": "MVP 目前僅提供 2881 富邦金固定測試資料"}, 404)
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/valuation":
            return self.send_json({"detail": "找不到此 API"}, 404)
        try:
            size = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(size) or b"{}")
            if str(payload.get("ticker", "2881")) != "2881":
                return self.send_json({"detail": "MVP 目前僅提供 2881 富邦金固定測試資料"}, 404)
            return self.send_json(self.valuation(payload))
        except (ValueError, json.JSONDecodeError) as exc:
            return self.send_json({"detail": str(exc)}, 400)

    @staticmethod
    def valuation(overrides):
        return calculate(
            PROVIDER.get_snapshot("2881"),
            PROVIDER.get_history("2881"),
            PROVIDER.get_forecasts("2881"),
            overrides,
        )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    print(f"台股估值比較：http://127.0.0.1:{port}")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
