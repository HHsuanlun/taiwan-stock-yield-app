from __future__ import annotations

import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from threading import Lock
from typing import Callable
from pathlib import Path

from .data.providers import COMMON_STOCKS, ETF_TICKERS


FINANCIAL_TICKERS = tuple(code for code in COMMON_STOCKS if code not in ETF_TICKERS)

class RankingService:
    """Build and briefly cache a fair-value ranking for the common financial list."""

    def __init__(
        self,
        valuation_loader: Callable[[str], dict],
        tickers: tuple[str, ...] = FINANCIAL_TICKERS,
        cache_seconds: int = 900,
        market_candidate_loader: Callable[[], dict] | None = None,
        snapshot_path: Path | None = None,
    ):
        self.valuation_loader = valuation_loader
        self.tickers = tickers
        self.cache_seconds = cache_seconds
        self.market_candidate_loader = market_candidate_loader
        self.snapshot_path = snapshot_path
        self._cache: tuple[float, dict] | None = None
        self._cache_lock = Lock()
        self._build_lock = Lock()

    def _cached(self) -> dict | None:
        with self._cache_lock:
            if self._cache and time.time() - self._cache[0] < self.cache_seconds:
                return self._cache[1]
        if self.snapshot_path and self.snapshot_path.exists():
            try:
                if time.time() - self.snapshot_path.stat().st_mtime < self.cache_seconds:
                    payload = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
                    with self._cache_lock:
                        self._cache = (time.time(), payload)
                    return payload
            except (OSError, ValueError):
                pass
        return None

    def _save_snapshot(self, result: dict) -> None:
        if not self.snapshot_path:
            return
        try:
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.snapshot_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.snapshot_path)
        except OSError:
            pass

    def get(self) -> dict:
        cached = self._cached()
        if cached:
            return cached
        with self._build_lock:
            cached = self._cached()
            if cached:
                return cached
            rows, errors, market_evaluated_rows, market_errors = [], [], [], []
            market_screen = None
            market_tickers = []
            if self.market_candidate_loader:
                try:
                    market_screen = self.market_candidate_loader()
                    market_tickers = [row["ticker"] for row in market_screen.get("finalists", [])]
                except Exception as error:
                    market_errors.append({"ticker": "market", "message": str(error)})
            evaluation_tickers = tuple(dict.fromkeys((*self.tickers, *market_tickers)))
            with ThreadPoolExecutor(max_workers=4) as pool:
                futures = {pool.submit(self.valuation_loader, ticker): ticker for ticker in evaluation_tickers}
                for future in as_completed(futures):
                    ticker = futures[future]
                    try:
                        value = future.result()
                        result_row = {
                            "ticker": value["ticker"],
                            "company_name": value["company_name"],
                            "current_price": round(float(value["current_price"]), 2),
                            "fair_value": round(float(value["fair_value"]), 2),
                            "upside_pct": round(float(value["upside_pct"]), 1),
                            "classification": value["classification"],
                            "confidence": value["confidence"],
                            "recommendation_qualification": value.get("recommendation_qualification"),
                        }
                        if ticker in self.tickers:
                            rows.append(result_row)
                        if ticker in market_tickers:
                            market_evaluated_rows.append(result_row)
                    except Exception as error:
                        target = market_errors if ticker in market_tickers and ticker not in self.tickers else errors
                        target.append({"ticker": ticker, "message": str(error)})
            rows.sort(key=lambda row: (-row["upside_pct"], row["ticker"]))
            for rank, row in enumerate(rows, 1):
                row["rank"] = rank
            market_rows = [row for row in market_evaluated_rows if (row.get("recommendation_qualification") or {}).get("passes_all")]
            market_rows.sort(key=lambda row: (-row["upside_pct"], row["ticker"]))
            reference = None
            if market_rows:
                winner = market_rows[0]
                reference = {
                    **winner,
                    "profile": "全台股模型適用第一名",
                    "selection_basis": market_screen["method"],
                    "method_note": "推薦代表模型合理價差第一，不等於保證上漲；仍須檢查產業循環、一次性盈餘與最新重大訊息。",
                    "qualification": winner["recommendation_qualification"],
                }
            result = {
                "basis": "中性合理價相對目前股價",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total": len(self.tickers),
                "available": len(rows),
                "rows": rows,
                "shareholder_earnings_reference": reference,
                "market_screen": {
                    "eligible_total": market_screen.get("eligible_total", 0) if market_screen else 0,
                    "finalist_total": len(market_tickers),
                    "valued_total": len(market_evaluated_rows),
                    "qualified_total": len(market_rows),
                    "as_of": market_screen.get("as_of") if market_screen else None,
                    "errors": market_errors,
                },
                "errors": errors,
            }
            with self._cache_lock:
                self._cache = (time.time(), result)
            self._save_snapshot(result)
            return result
