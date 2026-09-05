from __future__ import annotations

from statistics import median


DEFAULT_SUSTAINABLE_PB_CONFIG = {
    "recent_weights": [0.30, 0.25, 0.20, 0.12, 0.08, 0.05],
    "financial_sector_cost_of_equity": 0.09,
    "roe_sensitivity": 0.01,
    "cost_of_equity_floor": 0.075,
    "cost_of_equity_ceiling": 0.13,
    "growth_ceiling": 0.04,
    "divergence_warning": 0.15,
    "trend_adjustment_per_positive_flag": 0.002,
    "trend_adjustment_cap": 0.006,
}


def validate_accounting_basis(roe_basis: str, bps_basis: str) -> dict:
    return {"valid": roe_basis == bps_basis, "roe_basis": roe_basis, "bps_basis": bps_basis, "message": "一致" if roe_basis == bps_basis else "Accounting basis mismatch"}


def estimate_sustainable_roe(history: list[dict], operational_roe: float | None = None, trend_flags: dict | None = None, config: dict | None = None) -> dict:
    cfg = {**DEFAULT_SUSTAINABLE_PB_CONFIG, **(config or {})}
    observations = []
    ordered = sorted(history, key=lambda row: row["year"])
    for previous, current in zip(ordered, ordered[1:]):
        if current.get("eps") is None or previous.get("bps") is None or current.get("bps") is None:
            continue
        average_equity = (float(previous["bps"]) + float(current["bps"])) / 2
        if average_equity > 0:
            observations.append({"year": current["year"], "roe": float(current["eps"]) / average_equity})
    if operational_roe is not None:
        return {"reported_roe": observations[-1]["roe"] if observations else None, "normalized_roe": operational_roe, "sustainable_roe": operational_roe, "level": 1, "confidence": "Medium", "observations": observations, "reason": "以正常化營運獲利除以平均普通股權益估算。"}
    if not observations:
        return {"reported_roe": None, "normalized_roe": None, "sustainable_roe": None, "level": None, "confidence": "Low", "observations": [], "reason": "缺少足夠的歷史 EPS 與普通股權益資料。"}
    roe_values = [item["roe"] for item in observations]
    center = median(roe_values)
    deviations = [abs(value - center) for value in roe_values]
    mad = median(deviations) or 0.01
    lower, upper = max(0, center - 2.5 * mad), center + 2.5 * mad
    recent = list(reversed(observations))[: len(cfg["recent_weights"])]
    raw_weights = cfg["recent_weights"][: len(recent)]
    total = sum(raw_weights)
    normalized = sum(min(max(item["roe"], lower), upper) * weight for item, weight in zip(recent, raw_weights)) / total
    positive_flags = sum(bool(value) for value in (trend_flags or {}).values())
    trend_adjustment = min(positive_flags * cfg["trend_adjustment_per_positive_flag"], cfg["trend_adjustment_cap"])
    sustainable = normalized + trend_adjustment
    confidence = "Medium" if len(observations) >= 5 else "Low"
    reason = f"採最近 {len(recent)} 個完整年度 ROE 加權正常化；近期年度權重較高，以中位數／MAD 降低異常年度影響，再依 {positive_flags} 項正向營運趨勢調整 {trend_adjustment * 100:.1f} 個百分點。未使用 Forward EPS。"
    return {"reported_roe": observations[-1]["roe"], "historical_median_roe": center, "normalized_roe": normalized, "trend_adjustment": trend_adjustment, "sustainable_roe": sustainable, "level": 2, "confidence": confidence, "observations": observations, "reason": reason}


def estimate_cost_of_equity(forecast: dict, config: dict | None = None) -> dict:
    cfg = {**DEFAULT_SUSTAINABLE_PB_CONFIG, **(config or {})}
    risk_free, beta, erp = forecast.get("risk_free_rate"), forecast.get("beta"), forecast.get("equity_risk_premium")
    capm = float(risk_free) + float(beta) * float(erp) if risk_free is not None and beta is not None and erp is not None else None
    sector_prior = float(forecast.get("normalized_cost_of_equity", cfg["financial_sector_cost_of_equity"]))
    normalized = sector_prior if capm is None else max(sector_prior, capm)
    normalized = min(max(normalized, cfg["cost_of_equity_floor"]), cfg["cost_of_equity_ceiling"])
    return {"capm_cost_of_equity": capm, "normalized_cost_of_equity": normalized, "risk_free_rate": risk_free, "beta": beta, "equity_risk_premium": erp, "confidence": "Low" if capm is None else "Medium", "reason": "CAPM inputs unavailable; using a configurable financial-sector required-return prior." if capm is None else "CAPM 與金融業正常化要求報酬率取較保守者。"}


def estimate_long_term_growth(forecast: dict, cost_of_equity: float, config: dict | None = None) -> dict:
    cfg = {**DEFAULT_SUSTAINABLE_PB_CONFIG, **(config or {})}
    requested = float(forecast.get("long_term_growth_rate", 0.025))
    growth = min(requested, cfg["growth_ceiling"], cost_of_equity - 0.01)
    return {"growth_rate": max(0, growth), "confidence": "Medium" if "long_term_growth_rate" in forecast else "Low", "reason": "成熟期長期永續成長率，不是下一年度 EPS 成長率；並限制低於 cost of equity。"}


def calculate_fair_pb(sustainable_roe: float, growth_rate: float, cost_of_equity: float) -> float:
    if growth_rate >= cost_of_equity:
        raise ValueError("long-term growth must be lower than cost of equity")
    return max(0, (sustainable_roe - growth_rate) / (cost_of_equity - growth_rate))


def calculate_pb_fair_value(applicable_bps: float, fair_pb: float, basis_check: dict) -> float | None:
    return applicable_bps * fair_pb if basis_check["valid"] else None


def calculate_implied_roe(current_pb: float, growth_rate: float, cost_of_equity: float) -> float:
    return growth_rate + current_pb * (cost_of_equity - growth_rate)


def calculate_expectation_gap(implied_roe: float, sustainable_roe: float) -> float:
    return implied_roe - sustainable_roe


def calculate_sustainable_pb(history: list[dict], current_price: float, bps: float, forecast: dict, basis: str = "traditional", config: dict | None = None) -> dict:
    cfg = {**DEFAULT_SUSTAINABLE_PB_CONFIG, **(config or {})}
    roe = estimate_sustainable_roe(history, forecast.get("normalized_operational_roe"), forecast.get("fundamental_flags"), cfg)
    cost = estimate_cost_of_equity(forecast, cfg)
    growth = estimate_long_term_growth(forecast, cost["normalized_cost_of_equity"], cfg)
    basis_check = validate_accounting_basis(forecast.get("sustainable_roe_basis", "traditional"), basis)
    if roe["sustainable_roe"] is None:
        return {"status": "insufficient_data", "confidence": "Low", "basis_check": basis_check, "roe": roe, "cost_of_equity": cost, "growth": growth}
    sustainable_roe = roe["sustainable_roe"]
    fair_pb = calculate_fair_pb(sustainable_roe, growth["growth_rate"], cost["normalized_cost_of_equity"])
    fair_value = calculate_pb_fair_value(bps, fair_pb, basis_check)
    current_pb = current_price / bps
    implied_roe = calculate_implied_roe(current_pb, growth["growth_rate"], cost["normalized_cost_of_equity"])
    gap = calculate_expectation_gap(implied_roe, sustainable_roe)
    sensitivity = {
        "bear": calculate_fair_pb(max(growth["growth_rate"], sustainable_roe - cfg["roe_sensitivity"]), growth["growth_rate"], cost["normalized_cost_of_equity"]),
        "base": fair_pb,
        "bull": calculate_fair_pb(sustainable_roe + cfg["roe_sensitivity"], growth["growth_rate"], cost["normalized_cost_of_equity"]),
    }
    if gap > 0.015:
        expectation = "市場隱含的長期 ROE 明顯高於模型正常化估計，反映較高基本面期待。"
    elif gap > 0:
        expectation = "目前估值略高於模型基本面正常化估計，但 ROE 差距仍不算極端。"
    else:
        expectation = "市場定價尚未完全反映模型估計的正常化資本報酬能力。"
    return {"status": "active" if basis_check["valid"] else "basis_mismatch", "confidence": "Low" if cost["confidence"] == "Low" else roe["confidence"], "basis_check": basis_check, "roe": roe, "cost_of_equity": cost, "growth": growth, "current_pb": current_pb, "fair_pb": fair_pb if basis_check["valid"] else None, "fair_value": fair_value, "implied_roe": implied_roe, "expectation_gap": gap, "sensitivity_pb": sensitivity, "expectation": expectation}


def compare_independent_valuations(pe_value: float, pb_value: float | None, threshold: float = 0.15) -> dict:
    if pb_value is None:
        return {"difference_pct": None, "divergent": True, "message": "P/B 會計基礎或資料不足，暫時無法與 P/E 交叉驗證。"}
    difference = abs(pe_value - pb_value) / ((pe_value + pb_value) / 2)
    if difference > threshold:
        message = "P/E 與 P/B 估值差異較大，需要檢查正常化 EPS、Sustainable ROE、Cost of Equity 或 BPS 基礎；不應以簡單平均掩蓋差異。"
    else:
        message = "兩套獨立估值結果大致一致。"
    return {"difference_pct": difference, "divergent": difference > threshold, "message": message}
