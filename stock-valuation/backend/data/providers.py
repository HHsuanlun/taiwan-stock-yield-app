from __future__ import annotations

import json
import time
from datetime import date, timedelta
from threading import Lock
from typing import Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class StockDataProvider(Protocol):
    def get_snapshot(self, ticker: str) -> dict: ...

    def get_history(self, ticker: str) -> list[dict]: ...

    def get_forecasts(self, ticker: str) -> dict: ...


FINMIND_API = "https://api.finmindtrade.com/api/v4/data"
NAME_SOURCES = (
    "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
)
COMMON_STOCKS = {
    "2880": "華南金", "2881": "富邦金", "2882": "國泰金", "2883": "凱基金",
    "2884": "玉山金", "2885": "元大金", "2886": "兆豐金", "2887": "台新新光金",
    "2890": "永豐金", "2891": "中信金", "2892": "第一金", "5880": "合庫金",
    "0050": "元大台灣50", "0056": "元大高股息",
}
ETF_TICKERS = {"0050", "0056"}


class LiveStockProvider:
    """Free-data provider: FinMind first, exchange name lists, no paid API."""

    def __init__(self, cache_seconds: int = 900):
        self.cache_seconds = cache_seconds
        self._cache: dict[str, tuple[float, dict]] = {}
        self._names: tuple[float, dict[str, dict]] | None = None
        self._lock = Lock()

    @staticmethod
    def _json(url: str, timeout: int = 20):
        request = Request(url, headers={"User-Agent": "TaiwanStockValuation/2.7"})
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def _api(self, dataset: str, ticker: str, start_date: str) -> list[dict]:
        query = urlencode({"dataset": dataset, "data_id": ticker, "start_date": start_date})
        payload = self._json(f"{FINMIND_API}?{query}")
        rows = payload.get("data")
        if payload.get("status") != 200 or not isinstance(rows, list) or not rows:
            raise ValueError(payload.get("msg") or f"FinMind 未回傳 {dataset}")
        return rows

    def _yahoo_latest_price(self, ticker: str) -> tuple[float, str] | None:
        period1 = int(time.time()) - 14 * 86400
        for suffix in (".TW", ".TWO"):
            query = urlencode({"period1": period1, "period2": int(time.time()) + 86400, "interval": "1d"})
            try:
                payload = self._json(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}{suffix}?{query}", 10)
                result = payload.get("chart", {}).get("result", [None])[0]
                timestamps = result.get("timestamp", []) if result else []
                closes = result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if result else []
                valid = [(stamp, self._positive(close)) for stamp, close in zip(timestamps, closes) if self._positive(close)]
                if valid:
                    stamp, close = valid[-1]
                    return close, date.fromtimestamp(stamp).isoformat()
            except Exception:
                continue
        return None

    def stock_catalog(self) -> dict[str, dict]:
        if self._names and time.time() - self._names[0] < 86400:
            return self._names[1]
        with self._lock:
            if self._names and time.time() - self._names[0] < 86400:
                return self._names[1]
            result: dict[str, dict] = {code: {"name": name, "industry": "ETF" if code in ETF_TICKERS else "金融"} for code, name in COMMON_STOCKS.items()}
            for url in NAME_SOURCES:
                try:
                    for row in self._json(url, 8):
                        code = str(row.get("公司代號", "")).strip()
                        name = str(row.get("公司簡稱", "")).strip()
                        industry = str(row.get("產業別", row.get("產業類別", "台股"))).strip()
                        if code and name:
                            result[code] = {"name": name, "industry": industry or "台股"}
                except Exception:
                    continue
            if not result:
                raise ValueError("目前無法取得證交所／櫃買中心股票名單")
            self._names = (time.time(), result)
            return result

    def resolve(self, query: str) -> str:
        value = query.strip().upper().removesuffix(".TW").removesuffix(".TWO")
        catalog = self.stock_catalog()
        if value in catalog:
            return value
        exact = [code for code, item in catalog.items() if item["name"].casefold() == value.casefold()]
        if len(exact) == 1:
            return exact[0]
        partial = [code for code, item in catalog.items() if value and value.casefold() in item["name"].casefold()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            choices = "、".join(f"{code} {catalog[code]['name']}" for code in partial[:6])
            raise ValueError(f"名稱符合多檔股票，請輸入代號：{choices}")
        raise ValueError(f"找不到台股代號或名稱：{query}")

    @staticmethod
    def _positive(value):
        try:
            number = float(value)
            return number if number > 0 else None
        except (TypeError, ValueError):
            return None

    def _load(self, ticker: str) -> dict:
        cached = self._cache.get(ticker)
        if cached and time.time() - cached[0] < self.cache_seconds:
            return cached[1]
        if ticker in ETF_TICKERS:
            raise ValueError(f"{ticker} 是 ETF，沒有公司 EPS、BPS、ROE，因此不適用本頁的 P/E／P/B 股票估值模型；可至殖利率網站查詢配息與殖利率。")
        start = str(date.today() - timedelta(days=365 * 11))
        prices = self._api("TaiwanStockPrice", ticker, start)
        multiples = self._api("TaiwanStockPER", ticker, start)
        price_by_date = {row.get("date"): self._positive(row.get("close")) for row in prices}
        observations = []
        for row in multiples:
            close = price_by_date.get(row.get("date"))
            pe, pb = self._positive(row.get("PER")), self._positive(row.get("PBR"))
            if close and pe and pb:
                observations.append({"date": row["date"], "close": close, "pe": pe, "pb": pb, "eps": close / pe, "bps": close / pb})
        if not observations:
            raise ValueError("缺少可對齊的股價、P/E 與 P/B 資料")
        yearly: dict[int, dict] = {}
        for row in observations:
            yearly[int(row["date"][:4])] = row
        current_year = date.today().year
        complete = [
            {"year": year, "eps": row["eps"], "pe": row["pe"], "bps": row["bps"], "pb": row["pb"]}
            for year, row in sorted(yearly.items()) if year < current_year
        ][-10:]
        if len(complete) < 5:
            raise ValueError(f"只有 {len(complete)} 個完整年度有效資料，模型至少需要 5 年")
        latest = observations[-1]
        yahoo_price = self._yahoo_latest_price(ticker)
        current_price, price_date = yahoo_price if yahoo_price else (latest["close"], latest["date"])
        recent = observations[-504:]
        quarterly = [recent[index] for index in range(max(0, len(recent) - 63), -1, -63)][:8]
        quarterly.reverse()
        catalog = self.stock_catalog()
        info = catalog.get(ticker, {"name": ticker, "industry": "台股"})
        recent_eps = [row["eps"] for row in complete[-4:]]
        growth_rates = [recent_eps[i] / recent_eps[i - 1] - 1 for i in range(1, len(recent_eps)) if recent_eps[i - 1] > 0]
        growth_rates.sort()
        trend = growth_rates[len(growth_rates) // 2] if growth_rates else 0
        trend = min(max(trend, -0.15), 0.15)
        base_eps = latest["eps"] * (1 + trend * 0.5)
        dispersion = min(0.18, max(0.08, (max(recent_eps) - min(recent_eps)) / max(sum(recent_eps) / len(recent_eps), 0.01) * 0.20))
        forecast_bps = latest["bps"]
        eps_improving = len(recent_eps) >= 2 and recent_eps[-1] >= recent_eps[-2]
        bps_improving = len(complete) >= 2 and complete[-1]["bps"] >= complete[-2]["bps"]
        bundle = {
            "snapshot": {"ticker": ticker, "company_name": info["name"], "sector": info["industry"], "current_price": current_price, "as_of": price_date, "price_source": "Yahoo Finance" if yahoo_price else "FinMind"},
            "history": complete,
            "forecast": {
                "analyst_eps_low": base_eps * (1 - dispersion), "analyst_eps_median": base_eps, "analyst_eps_high": base_eps * (1 + dispersion),
                "forecast_bps": forecast_bps, "adjusted_bps": forecast_bps,
                "recent_quarterly_pb": [row["pb"] for row in quarterly], "recent_pb_source": "FinMind recent observations",
                "recent_quarterly_pe": [row["pe"] for row in quarterly], "recent_pe_source": "FinMind recent observations",
                "pb_fundamental_flags": {"roe_stable_or_improving": eps_improving, "bps_positive_trend": bps_improving, "dividend_stable_or_improving": False, "capital_or_asset_quality_acceptable": True},
                "fundamental_flags": {"eps_stable_or_improving": eps_improving, "bps_improving": bps_improving, "roe_stable_or_improving": eps_improving, "dividend_stable_or_improving": False},
                "book_value_quality_score": 0.65, "book_value_quality_note": "免費公開資料自動估算", "accounting_comparability_score": 0.8,
                "normalized_roe": complete[-1]["eps"] / ((complete[-2]["bps"] + complete[-1]["bps"]) / 2),
                "normalized_roe_basis": "traditional", "adjusted_bps_basis": "traditional", "sustainable_roe_basis": "traditional",
                "long_term_growth_rate": 0.025, "roe_pb_confidence": 0.5, "accounting_regime_change": False,
                "as_of": latest["date"], "data_method": "Yahoo 優先取得最新股價；FinMind 提供歷史股價與 PER/PBR 對齊。EPS=股價/PER，BPS=股價/PBR；預估 EPS 依最新公告口徑與近年趨勢正常化。",
            },
        }
        self._cache[ticker] = (time.time(), bundle)
        return bundle

    def get_snapshot(self, ticker: str) -> dict:
        return dict(self._load(ticker)["snapshot"])

    def get_history(self, ticker: str) -> list[dict]:
        return [dict(row) for row in self._load(ticker)["history"]]

    def get_forecasts(self, ticker: str) -> dict:
        return dict(self._load(ticker)["forecast"])


class FixtureProvider:
    """Milestone 1 deterministic data provider. Values are illustrative fixtures."""

    _snapshot = {
        "ticker": "2881",
        "company_name": "富邦金",
        "sector": "金融",
        "current_price": 150.50,
        "as_of": "2026-09-04",
    }
    _forecast = {
        "analyst_eps_low": 9.94,
        "analyst_eps_median": 10.95,
        "analyst_eps_high": 11.86,
        "forecast_bps": 83.7,
        "adjusted_bps": 109.3,
        "recent_quarterly_pb": [1.45, 1.49, 1.52, 1.55, 1.56, 1.59, 1.62, 1.66],
        "recent_pb_source": "recent_8q",
        "pb_fundamental_flags": {
            "roe_stable_or_improving": False,
            "bps_positive_trend": True,
            "dividend_stable_or_improving": False,
            "capital_or_asset_quality_acceptable": True,
        },
        "book_value_quality_score": 1.0,
        "book_value_quality_note": "資料不足，MVP 預設假設",
        "accounting_comparability_score": 0.6,
        "normalized_roe": 0.11,
        "normalized_roe_basis": "adjusted",
        "adjusted_bps_basis": "adjusted",
        "long_term_growth_rate": 0.03,
        "roe_pb_confidence": 0.55,
        "recent_quarterly_pe": [12.0, 12.3, 12.5, 12.7, 13.0, 13.2, 13.4, 13.6],
        "recent_pe_source": "recent_8q",
        "fundamental_flags": {
            "eps_stable_or_improving": True,
            "bps_improving": True,
            "roe_stable_or_improving": False,
            "dividend_stable_or_improving": False,
        },
        "accounting_regime_change": True,
        "as_of": "2026-09-04",
    }
    _history = [
        {"year": 2016, "eps": 4.73, "pe": 10.78, "bps": 44.1, "pb": 1.29},
        {"year": 2017, "eps": 5.19, "pe": 9.77, "bps": 47.2, "pb": 1.12},
        {"year": 2018, "eps": 4.52, "pe": 10.41, "bps": 48.7, "pb": 1.18},
        {"year": 2019, "eps": 5.46, "pe": 8.50, "bps": 52.6, "pb": 0.88},
        {"year": 2020, "eps": 8.54, "pe": 5.47, "bps": 56.8, "pb": 0.70},
        {"year": 2021, "eps": 12.49, "pe": 6.11, "bps": 66.3, "pb": 1.08},
        {"year": 2022, "eps": 3.54, "pe": 15.9, "bps": 50.1, "pb": 1.39},
        {"year": 2023, "eps": 4.80, "pe": 13.50, "bps": 54.9, "pb": 1.18},
        {"year": 2024, "eps": 10.77, "pe": 8.38, "bps": 65.4, "pb": 1.45},
        {"year": 2025, "eps": 8.37, "pe": 11.48, "bps": 72.2, "pb": 1.53},
    ]

    def _ensure(self, ticker: str) -> None:
        if ticker != "2881":
            raise KeyError("MVP 目前僅提供 2881 富邦金固定測試資料")

    def get_snapshot(self, ticker: str) -> dict:
        self._ensure(ticker)
        return dict(self._snapshot)

    def get_history(self, ticker: str) -> list[dict]:
        self._ensure(ticker)
        return [dict(row) for row in self._history]

    def get_forecasts(self, ticker: str) -> dict:
        self._ensure(ticker)
        return dict(self._forecast)
