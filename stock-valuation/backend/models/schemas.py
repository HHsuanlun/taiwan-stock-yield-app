from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class HistoricalPoint(BaseModel):
    year: int
    eps: float | None = None
    pe: float | None = None
    bps: float | None = None
    pb: float | None = None


class ValuationRequest(BaseModel):
    ticker: str = "2881"
    forecast_eps: float | None = None
    forecast_eps_low: float | None = None
    forecast_eps_high: float | None = None
    forecast_bps: float | None = None
    regression_weight: float = Field(0.25, ge=0)
    recent_weight: float = Field(0.45, ge=0)
    historical_weight: float = Field(0.30, ge=0)
    pe_weight: float = Field(0.50, ge=0)
    pb_weight: float = Field(0.50, ge=0)
    weights_are_final: bool = False
    pe_spread: float | None = Field(None, ge=0)

    @model_validator(mode="after")
    def validate_weights(self):
        if self.regression_weight + self.recent_weight + self.historical_weight <= 0:
            raise ValueError("P/E 參考權重總和必須大於 0")
        if self.pe_weight + self.pb_weight <= 0:
            raise ValueError("P/E 與 P/B 模型權重總和必須大於 0")
        return self


class ValuationResult(BaseModel):
    ticker: str
    company_name: str
    current_price: float
    fair_pe: float
    pe_target_price: float
    fair_pb: float
    pb_target_price: float
    fair_value: float
    composite: dict[str, Any]
    bear_value: float
    bull_value: float
    upside_pct: float
    implied_forward_pe: float
    classification: str
    confidence: str
    valuation_heat: dict[str, Any]
    capital_efficiency: dict[str, Any]
    cross_validation: dict[str, Any]
    historical: list[HistoricalPoint]
    assumptions: dict[str, Any]
    source_notes: list[dict[str, str]]
    model_version: str
