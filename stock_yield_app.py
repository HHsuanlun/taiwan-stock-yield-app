"""本機網頁 App：查詢台股現金股利與預估殖利率。

執行：python stock_yield_app.py
瀏覽器開啟：http://127.0.0.1:8000
"""
from __future__ import annotations

import importlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = importlib.import_module("更新金融股股利")
STOCK_NAMES = {
    "2880": "華南金", "2881": "富邦金", "2882": "國泰金", "2883": "凱基金",
    "2884": "玉山金", "2885": "元大金", "2886": "兆豐金", "2887": "台新新光金",
    "2890": "永豐金", "2891": "中信金", "2892": "第一金", "5880": "合庫金",
    "0050": "元大台灣50", "0056": "元大高股息", "4938": "和碩",
}
CACHE: dict[str, tuple[float, dict]] = {}
NAME_CACHE: tuple[float, dict[str, str]] | None = None
NAME_CACHE_LOCK = Lock()
NAME_CACHE_SECONDS = 24 * 60 * 60
OFFICIAL_NAME_SOURCES = (
    "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
)


def official_stock_names() -> dict[str, str]:
    """讀取交易所公開名單，將 Yahoo 的英文名稱換成中文簡稱（快取 24 小時）。"""
    global NAME_CACHE
    if NAME_CACHE and time.time() - NAME_CACHE[0] < NAME_CACHE_SECONDS:
        return NAME_CACHE[1]
    with NAME_CACHE_LOCK:
        if NAME_CACHE and time.time() - NAME_CACHE[0] < NAME_CACHE_SECONDS:
            return NAME_CACHE[1]
        names: dict[str, str] = {}
        for source in OFFICIAL_NAME_SOURCES:
            try:
                request = Request(source, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(request, timeout=5) as response:
                    records = json.loads(response.read().decode("utf-8"))
                for record in records:
                    code = str(record.get("公司代號", "")).strip()
                    name = str(record.get("公司簡稱", "")).strip()
                    if code and name:
                        names[code] = name
            except Exception:
                continue
        NAME_CACHE = (time.time(), names)
        return names


def preferred_stock_name(code: str) -> str:
    return STOCK_NAMES.get(code) or official_stock_names().get(code) or code


def merge_missing_finmind_cash(finmind_rows: list[dict], yahoo_rows: list[dict]) -> tuple[list[dict], bool]:
    """只以 Yahoo 補上 FinMind 已標記為疑似缺漏的年度現金股利，股票股利仍保留 FinMind 資料。"""
    yahoo_by_year = {row["issueYear"]: row for row in yahoo_rows}
    merged: list[dict] = []
    corrected = False
    for row in finmind_rows:
        yahoo_row = yahoo_by_year.get(row["issueYear"])
        if not row.get("dataNeedsYahooCheck") or not yahoo_row or yahoo_row["cashDividend"] <= row["cashDividend"] + 0.0001:
            merged.append(row)
            continue
        item = dict(row)
        item["cashDividend"] = yahoo_row["cashDividend"]
        item["totalDividend"] = item["cashDividend"] + item["stockDividend"]
        current_metrics = DATA.dividend_metrics(item.get("currentPrice"), item["cashDividend"], item["stockDividend"])
        average_metrics = DATA.dividend_metrics(item.get("averagePrice"), item["cashDividend"], item["stockDividend"])
        item["currentCashYield"] = item["cashDividend"] / item["currentPrice"] * 100 if item.get("currentPrice") else None
        item["averageCashYield"] = item["cashDividend"] / item["averagePrice"] * 100 if item.get("averagePrice") else None
        item["currentTotalDividendYield"] = current_metrics["totalDividendYield"]
        item["averageTotalDividendYield"] = average_metrics["totalDividendYield"]
        item["exRightPrice"] = current_metrics["exRightPrice"]
        item["stockDividendValue"] = current_metrics["stockDividendValue"]
        item["totalDividendValue"] = current_metrics["totalDividendValue"]
        item["dataNote"] = "Yahoo Finance 校正：補入 FinMind 疑似缺漏的年度現金股利。"
        merged.append(item)
        corrected = True
    return merged, corrected


def query_stock(code: str) -> dict:
    """取得一檔股票的摘要與近年股利；同代號 10 分鐘內直接使用快取。"""
    cached = CACHE.get(code)
    if cached and time.time() - cached[0] < 600:
        return cached[1]
    name = preferred_stock_name(code)
    offline = False
    source_fallback = False
    try:
        rows = DATA.fetch_rows(code, name)
        if any(row.get("dataNeedsYahooCheck") for row in rows):
            try:
                rows, source_fallback = merge_missing_finmind_cash(rows, DATA.fetch_yahoo_rows(code, name))
            except Exception:
                pass
    except Exception as finmind_error:
        try:
            rows = DATA.fetch_yahoo_rows(code, name)
            source_fallback = True
        except Exception as yahoo_error:
            rows = DATA.fallback_rows(code, name)
            offline = True
            if not rows:
                raise ValueError(f"無法取得 {code} 的資料：FinMind：{finmind_error}；Yahoo Finance：{yahoo_error}") from yahoo_error
    rows.sort(key=lambda row: row["issueYear"], reverse=True)
    latest = rows[0]
    annual_yields = [row["averageTotalDividendYield"] / 100 for row in rows if row.get("averageTotalDividendYield") is not None and row["issueYear"] >= latest["issueYear"] - 4]
    annual_cash_yields = [row["averageCashYield"] / 100 for row in rows if row.get("averageCashYield") is not None and row["issueYear"] >= latest["issueYear"] - 4]
    payload = {
        "code": code,
        "name": latest.get("stockName", name),
        "price": latest.get("currentPrice"),
        "cashDividend": latest.get("cashDividend"),
        "stockDividend": latest.get("stockDividend"),
        "exRightPrice": latest.get("exRightPrice"),
        "stockDividendValue": latest.get("stockDividendValue"),
        "totalDividendValue": latest.get("totalDividendValue"),
        "issueYear": latest.get("issueYear"),
        "estimatedYield": latest.get("currentTotalDividendYield", 0) / 100 if latest.get("currentTotalDividendYield") is not None else None,
        "cashEstimatedYield": latest["cashDividend"] / latest["currentPrice"] if latest.get("currentPrice") else None,
        "fiveYearYield": sum(annual_yields) / len(annual_yields) if annual_yields else None,
        "fiveYearCashYield": sum(annual_cash_yields) / len(annual_cash_yields) if annual_cash_yields else None,
        "offline": offline,
        "sourceFallback": source_fallback,
        "source": latest.get("sourceUrl"),
        "history": rows[:15],
    }
    CACHE[code] = (time.time(), payload)
    return payload


def query_stocks(codes: list[str]) -> dict:
    """批次查詢並依目前預估殖利率由高至低排序。"""
    stocks, errors = [], []
    unique_codes = list(dict.fromkeys(codes))
    with ThreadPoolExecutor(max_workers=min(6, len(unique_codes))) as pool:
        futures = {pool.submit(query_stock, code): code for code in unique_codes}
        for future in as_completed(futures):
            code = futures[future]
            try:
                stocks.append(future.result())
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
            if not codes or len(codes) > 20 or any(not code.isdigit() or not 4 <= len(code) <= 6 for code in codes):
                self.send_json({"error": "請輸入 1 至 20 檔、每檔 4 至 6 碼的股票代號。"}, 400)
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
