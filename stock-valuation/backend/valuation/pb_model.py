from __future__ import annotations

from statistics import mean, median

from .pe_model import clamp, percentile


DEFAULT_PB_CONFIG = {
    "historical_weight": 0.40,
    "recent_weight": 0.60,
    "regime_threshold": 0.10,
    "strength_full_scale": 0.30,
    "min_regime_weight": 0.20,
    "max_regime_weight": 0.70,
    "accounting_change_max_weight": 0.80,
    "minimum_persistence": 0.50,
    "partial_persistence": 0.67,
    "partial_weight_cap": 0.40,
    "minimum_spread": 0.05,
    "maximum_spread": 0.30,
    "bps_uncertainty": 0.05,
}


def pb_fundamental_score(flags: dict | None) -> float:
    flags = flags or {}
    return (
        0.30 * bool(flags.get("roe_stable_or_improving"))
        + 0.30 * bool(flags.get("bps_positive_trend"))
        + 0.20 * bool(flags.get("dividend_stable_or_improving"))
        + 0.20 * bool(flags.get("capital_or_asset_quality_acceptable"))
    )


def calculate_pb_model(history: list[dict], current_price: float, forecast: dict, config: dict | None = None) -> dict:
    cfg = {**DEFAULT_PB_CONFIG, **(config or {})}
    historical = [float(row["pb"]) for row in history[-10:] if row.get("pb") is not None]
    if len(historical) < 5:
        raise ValueError("P/B 模型至少需要 5 年傳統 P/B 歷史資料")
    hist_median, hist_mean = median(historical), mean(historical)
    recent_median = median(historical[-3:])
    historical_fair = hist_median * cfg["historical_weight"] + recent_median * cfg["recent_weight"]

    regime_values = [float(value) for value in forecast.get("recent_quarterly_pb", []) if value and value > 0]
    regime_available = len(regime_values) >= 4
    regime_median = regime_mad = regime_p10 = regime_p90 = None
    ratio = persistence = strength = raw_weight = regime_weight = 0.0
    direction = "unavailable"
    f_score = pb_fundamental_score(forecast.get("pb_fundamental_flags"))
    if regime_available:
        regime_p10, regime_p90 = percentile(regime_values, 0.10), percentile(regime_values, 0.90)
        winsorized = [clamp(value, regime_p10, regime_p90) for value in regime_values]
        regime_median = median(winsorized)
        regime_mad = median([abs(value - regime_median) for value in winsorized])
        ratio = regime_median / historical_fair
        band = cfg["regime_threshold"]
        if ratio > 1 + band:
            direction = "positive"
            count = sum(value > historical_fair * (1 + band) for value in regime_values)
        elif ratio < 1 - band:
            direction = "negative"
            count = sum(value < historical_fair * (1 - band) for value in regime_values)
        else:
            direction, count = "none", 0
        persistence = count / len(regime_values)
        strength = abs(ratio - 1) * persistence
        if direction != "none" and persistence >= cfg["minimum_persistence"]:
            max_weight = cfg["accounting_change_max_weight"] if forecast.get("accounting_regime_change") else cfg["max_regime_weight"]
            raw_weight = cfg["min_regime_weight"] + clamp(strength / cfg["strength_full_scale"], 0, 1) * (max_weight - cfg["min_regime_weight"])
            if persistence < cfg["partial_persistence"]:
                raw_weight = min(raw_weight, cfg["partial_weight_cap"])
            regime_weight = raw_weight * (0.5 + 0.5 * f_score)

    final_pb = historical_fair * (1 - regime_weight) + (regime_median or historical_fair) * regime_weight
    pb_mad = median([abs(value - hist_median) for value in historical])
    spread = clamp(0.8 * pb_mad, cfg["minimum_spread"], cfg["maximum_spread"])
    historical_p10, historical_p90 = percentile(historical, 0.10), percentile(historical, 0.90)
    lower, upper = historical_p10 * 0.90, historical_p90 * 1.10
    if regime_weight > 0 and regime_p10 is not None and regime_p90 is not None:
        lower = min(lower, regime_p10 * 0.95)
        upper = max(upper, regime_p90 * 1.05)
    bear_pb, bull_pb = max(final_pb - spread, lower), min(final_pb + spread, upper)

    bps = float(forecast["forecast_bps"])
    adjusted_bps = float(forecast["adjusted_bps"])
    uncertainty = cfg["bps_uncertainty"]
    bps_scenarios = {"bear": bps * (1 - uncertainty), "base": bps, "bull": bps * (1 + uncertainty)}
    pb_scenarios = {"bear": bear_pb, "base": final_pb, "bull": bull_pb}
    matrix = [
        {"scenario": name, "bps": round(value, 2), "prices": {pb_name: round(value * pb, 2) for pb_name, pb in pb_scenarios.items()}}
        for name, value in bps_scenarios.items()
    ]

    hist_score = 1.0 if len(historical) >= 10 else 0.7
    regime_score = 1.0 if len(regime_values) >= 8 else 0.7 if len(regime_values) >= 4 else 0.4
    quality = float(forecast.get("book_value_quality_score", 1.0))
    comparability = float(forecast.get("accounting_comparability_score", 0.5))
    confidence_score = 0.20 * hist_score + 0.20 * regime_score + 0.15 * persistence + 0.20 * f_score + 0.15 * quality + 0.10 * comparability
    confidence = "高" if confidence_score >= 0.75 else "中" if confidence_score >= 0.50 else "低"

    current_traditional_pb = current_price / bps
    current_adjusted_pb = current_price / adjusted_bps
    return {
        "traditional": {
            "historical_median": hist_median, "historical_mean": hist_mean, "recent_median": recent_median,
            "historical_fair_pb": historical_fair, "current_regime_pb": regime_median, "regime_source": forecast.get("recent_pb_source") if regime_available else None,
            "regime_ratio": ratio, "direction": direction, "persistence_score": persistence, "rerating_strength": strength,
            "fundamental_score": f_score, "book_value_quality_score": quality, "book_value_quality_note": forecast.get("book_value_quality_note", ""),
            "accounting_comparability_score": comparability, "raw_regime_weight": raw_weight, "regime_weight": regime_weight, "historical_weight": 1 - regime_weight,
            "final_fair_pb": final_pb, "pb_mad": pb_mad, "spread": spread, "bear_pb": bear_pb, "base_pb": final_pb, "bull_pb": bull_pb,
            "current_pb": current_traditional_pb, "premium_to_historical_pct": (current_traditional_pb / historical_fair - 1) * 100,
            "premium_to_final_pct": (current_traditional_pb / final_pb - 1) * 100, "required_bps": current_price / final_pb,
            "target_prices": {"bear": bps_scenarios["bear"] * bear_pb, "base": bps * final_pb, "bull": bps_scenarios["bull"] * bull_pb},
            "valuation_matrix": matrix, "confidence_score": confidence_score, "confidence": confidence,
        },
        "adjusted": {
            "bps": adjusted_bps, "current_pb": current_adjusted_pb, "historical_fair_pb": None, "current_regime_pb": None,
            "final_fair_pb": None, "target_price": None, "confidence": "低", "confidence_score": 0.20,
            "status": "長期 adjusted P/B 歷史不足；未套用 traditional P/B 倍數",
        },
        "bps_scenarios": {key: round(value, 2) for key, value in bps_scenarios.items()},
        "pb_scenarios": {key: round(value, 3) for key, value in pb_scenarios.items()},
    }
