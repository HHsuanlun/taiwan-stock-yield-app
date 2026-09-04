from __future__ import annotations

from typing import Protocol


class StockDataProvider(Protocol):
    def get_snapshot(self, ticker: str) -> dict: ...

    def get_history(self, ticker: str) -> list[dict]: ...

    def get_forecasts(self, ticker: str) -> dict: ...


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
