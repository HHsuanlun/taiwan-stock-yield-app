from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

from .data.providers import COMMON_STOCKS, ETF_TICKERS


FINANCIAL_TICKERS = tuple(code for code in COMMON_STOCKS if code not in ETF_TICKERS)

# Life-insurance-exposed financial holdings for which reported EPS and realized
# FVOCI equity gains should be read separately.  The reference still ranks on
# Primary fair value; it does not capitalize the non-recurring gain at a P/E.
SHAREHOLDER_EARNINGS_PROFILES = {
    "2881": "壽險型金控",
    "2882": "壽險型金控",
    "2883": "壽險／證券型金控",
    "2885": "證券型金控（須確認 FVOCI 揭露重大性）",
    "2887": "含壽險金控（須確認合併後揭露口徑）",
    "2891": "含壽險金控",
}


class RankingService:
    """Build and briefly cache a fair-value ranking for the common financial list."""

    def __init__(
        self,
        valuation_loader: Callable[[str], dict],
        tickers: tuple[str, ...] = FINANCIAL_TICKERS,
        cache_seconds: int = 900,
    ):
        self.valuation_loader = valuation_loader
        self.tickers = tickers
        self.cache_seconds = cache_seconds
        self._cache: tuple[float, dict] | None = None
        self._cache_lock = Lock()
        self._build_lock = Lock()

    def _cached(self) -> dict | None:
        with self._cache_lock:
            if self._cache and time.time() - self._cache[0] < self.cache_seconds:
                return self._cache[1]
        return None

    def get(self) -> dict:
        cached = self._cached()
        if cached:
            return cached
        with self._build_lock:
            cached = self._cached()
            if cached:
                return cached
            rows, errors = [], []
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(self.valuation_loader, ticker): ticker for ticker in self.tickers}
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        value = future.result()
                        rows.append({
                            "ticker": value["ticker"],
                            "company_name": value["company_name"],
                            "current_price": round(float(value["current_price"]), 2),
                            "fair_value": round(float(value["fair_value"]), 2),
                            "upside_pct": round(float(value["upside_pct"]), 1),
                            "classification": value["classification"],
                            "confidence": value["confidence"],
                        })
                    except Exception as error:
                        errors.append({"ticker": ticker, "message": str(error)})
            rows.sort(key=lambda row: (-row["upside_pct"], row["ticker"]))
            for rank, row in enumerate(rows, 1):
                row["rank"] = rank
            reference_candidates = [row for row in rows if row["ticker"] in SHAREHOLDER_EARNINGS_PROFILES]
            reference = None
            if reference_candidates:
                winner = reference_candidates[0]
                reference = {
                    **winner,
                    "profile": SHAREHOLDER_EARNINGS_PROFILES[winner["ticker"]],
                    "selection_basis": "適用正式 EPS＋已實現 FVOCI 分開觀察，並以 Primary 中性合理價差排序",
                    "method_note": "正式 EPS 仍用於 P/E；已實現 FVOCI 僅作股東可分配獲利／BPS 檢核，避免重複計算。",
                    "eligible_tickers": list(SHAREHOLDER_EARNINGS_PROFILES),
                }
            result = {
                "basis": "中性合理價相對目前股價",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total": len(self.tickers),
                "available": len(rows),
                "rows": rows,
                "shareholder_earnings_reference": reference,
                "errors": errors,
            }
            with self._cache_lock:
                self._cache = (time.time(), result)
            return result
