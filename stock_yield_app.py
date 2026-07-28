"""本機網頁 App：查詢台股現金股利與預估殖利率。

執行：python stock_yield_app.py
瀏覽器開啟：http://127.0.0.1:8000
"""
from __future__ import annotations

import importlib
import json
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
DATA = importlib.import_module("更新金融股股利")
STOCK_NAMES = {"2891": "中信金", "5880": "合庫金", "2880": "華南金"}
CACHE: dict[str, tuple[float, dict]] = {}


def query_stock(code: str) -> dict:
    """取得一檔股票的摘要與近年股利；同代號 10 分鐘內直接使用快取。"""
    import time

    cached = CACHE.get(code)
    if cached and time.time() - cached[0] < 600:
        return cached[1]
    name = STOCK_NAMES.get(code, code)
    offline = False
    try:
        rows = DATA.fetch_rows(code, name)
    except Exception as error:
        rows = DATA.fallback_rows(code, name)
        offline = True
        if not rows:
            raise ValueError(f"無法取得 {code} 的資料：{error}") from error
    rows.sort(key=lambda row: row["issueYear"], reverse=True)
    latest = rows[0]
    annual_yields = [row["averageCashYield"] / 100 for row in rows if row.get("averageCashYield") is not None and row["issueYear"] >= latest["issueYear"] - 4]
    payload = {
        "code": code,
        "name": latest.get("stockName", name),
        "price": latest.get("currentPrice"),
        "cashDividend": latest.get("cashDividend"),
        "issueYear": latest.get("issueYear"),
        "estimatedYield": latest["cashDividend"] / latest["currentPrice"] if latest.get("currentPrice") else None,
        "fiveYearYield": sum(annual_yields) / len(annual_yields) if annual_yields else None,
        "offline": offline,
        "source": latest.get("sourceUrl"),
        "history": rows[:15],
    }
    CACHE[code] = (time.time(), payload)
    return payload


def query_stocks(codes: list[str]) -> dict:
    """批次查詢並依目前預估殖利率由高至低排序。"""
    stocks, errors = [], []
    for code in dict.fromkeys(codes):
        try:
            stocks.append(query_stock(code))
        except ValueError as error:
            errors.append({"code": code, "message": str(error)})
    stocks.sort(key=lambda stock: stock["estimatedYield"] if stock["estimatedYield"] is not None else -1, reverse=True)
    return {"stocks": stocks, "errors": errors}


class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/stock":
            code = parse_qs(parsed.query).get("code", [""])[0].strip()
            if not code.isdigit() or not 4 <= len(code) <= 6:
                self.send_json({"error": "請輸入 4 至 6 碼股票代號。"}, 400)
                return
            try:
                self.send_json(query_stock(code))
            except ValueError as error:
                self.send_json({"error": str(error)}, 502)
            return
        if parsed.path == "/api/stocks":
            raw_codes = parse_qs(parsed.query).get("codes", [""])[0]
            codes = [code.strip() for code in raw_codes.split(",") if code.strip()]
            if not codes or len(codes) > 12 or any(not code.isdigit() or not 4 <= len(code) <= 6 for code in codes):
                self.send_json({"error": "請輸入 1 至 12 檔、每檔 4 至 6 碼的股票代號。"}, 400)
                return
            self.send_json(query_stocks(codes))
            return
        if parsed.path in {"/", "/index.html"}:
            self.path = "/stock_yield_app.html"
        return super().do_GET()

    def send_json(self, data: dict, status: int = 200):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), AppHandler)
    print(f"App 已啟動：http://127.0.0.1:{port}（按 Ctrl+C 停止）")
    server.serve_forever()
