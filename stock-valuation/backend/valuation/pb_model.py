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
    "comparability_factor_min": 0.75,
    "comparability_factor_max": 1.00,
    "provisional_bridge_weight": 0.40,
    "provisional_roe_weight": 0.40,
    "provisional_peer_weight": 0.20,
    "provisional_confidence_cap": 0.65,
    "provisional_pb_family_weight_cap": 0.30,
    "provisional_minimum_spread": 0.10,
    "growth_rate_min": 0.00,
    "growth_rate_max": 0.05,
    "base_required_return": 0.10,
}


def pb_fundamental_score(flags: dict | None) -> float:
    flags = flags or {}
    return (
        0.30 * bool(flags.get("roe_stable_or_improving"))
        + 0.30 * bool(flags.get("bps_positive_trend"))
        + 0.20 * bool(flags.get("dividend_stable_or_improving"))
        + 0.20 * bool(flags.get("capital_or_asset_quality_acceptable"))
    )


def calculate_adjusted_pb_layer(
    adjusted_bps: float,
    current_price: float,
    traditional: dict,
    forecast: dict,
    cfg: dict,
) -> dict:
    observations = [float(value) for value in forecast.get("adjusted_pb_observations", []) if value and value > 0]
    observation_count = len(observations)
    current_pb = current_price / adjusted_bps
    current_traditional_pb = traditional["current_pb"]
    common = {
        "bps": adjusted_bps,
        "current_pb": current_pb,
        "historical_observation_count": observation_count,
        "discount_vs_traditional_pct": (current_pb / current_traditional_pb - 1) * 100,
        "current_pb_used_as_anchor": False,
    }

    if observation_count >= 4:
        fair_pb = median(observations)
        adjusted_mad = median([abs(value - fair_pb) for value in observations])
        multiplier = 1.0 if observation_count >= 8 else 1.25
        adjusted_spread = max(cfg["minimum_spread"], adjusted_mad * 0.8 * multiplier)
        score = min(0.85 if observation_count >= 8 else 0.65, 0.35 + observation_count * 0.06)
        status = "active" if observation_count >= 8 else "experimental"
        return {
            **common,
            "status": status,
            "status_label": "正式 Adjusted P/B 模型" if status == "active" else "實驗性 Adjusted P/B 模型",
            "anchors": None,
            "provisional": None,
            "fair_pb": fair_pb,
            "fair_value": adjusted_bps * fair_pb,
            "bear_pb": max(0, fair_pb - adjusted_spread),
            "bull_pb": fair_pb + adjusted_spread,
            "confidence": "高" if score >= 0.75 else "中",
            "confidence_score": score,
            "included_in_expanded_composite": True,
            "warning": "此模型使用自身可比較的 Adjusted P/B 觀測資料，未套用 Traditional P/B 倍數。",
        }

    comparability = traditional["accounting_comparability_score"]
    factor_range = cfg["comparability_factor_max"] - cfg["comparability_factor_min"]
    comparability_factor = cfg["comparability_factor_min"] + factor_range * comparability
    bridge_pb = traditional["final_fair_pb"] * comparability_factor
    bridge_confidence = (
        0.40 * comparability
        + 0.40 * traditional["confidence_score"]
        + 0.20 * traditional["book_value_quality_score"]
    )

    normalized_roe = forecast.get("normalized_roe")
    growth_rate = clamp(
        float(forecast.get("long_term_growth_rate", 0.03)),
        cfg["growth_rate_min"],
        cfg["growth_rate_max"],
    )
    required_return = float(forecast.get("required_return", cfg["base_required_return"]))
    roe_anchor = None
    if normalized_roe is not None and float(normalized_roe) > growth_rate and required_return > growth_rate:
        roe_pb = (float(normalized_roe) - growth_rate) / (required_return - growth_rate)
        roe_anchor = {
            "pb": roe_pb,
            "confidence": float(forecast.get("roe_pb_confidence", 0.50)),
            "normalized_roe": float(normalized_roe),
            "growth_rate": growth_rate,
            "required_return": required_return,
            "required_return_is_assumption": "required_return" not in forecast,
        }

    peer_anchor = forecast.get("peer_adjusted_pb_anchor")
    anchors = {
        "traditional_bridge": {
            "pb": bridge_pb,
            "confidence": bridge_confidence,
            "comparability_factor": comparability_factor,
            "accounting_comparability_score": comparability,
        },
        "roe_based": roe_anchor,
        "peer": peer_anchor,
    }
    candidates = [
        ("traditional_bridge", anchors["traditional_bridge"], cfg["provisional_bridge_weight"]),
        ("roe_based", roe_anchor, cfg["provisional_roe_weight"]),
        ("peer", peer_anchor, cfg["provisional_peer_weight"]),
    ]
    available = [(name, anchor, weight) for name, anchor, weight in candidates if anchor is not None]
    base_total = sum(weight for _, _, weight in available)
    effective = [(name, anchor, weight / base_total * anchor["confidence"]) for name, anchor, weight in available]
    effective_total = sum(weight for _, _, weight in effective)
    normalized_weights = {name: weight / effective_total for name, _, weight in effective}
    provisional_pb = sum(anchor["pb"] * normalized_weights[name] for name, anchor, _ in effective)

    uncertainty_multiplier = 1.75 if observation_count == 0 else 1.50 if observation_count == 1 else 1.25
    provisional_spread = max(traditional["spread"], cfg["provisional_minimum_spread"]) * uncertainty_multiplier
    bear_pb = max(0, provisional_pb - provisional_spread)
    bull_pb = provisional_pb + provisional_spread
    anchor_confidence = sum(anchor["confidence"] * normalized_weights[name] for name, anchor, _ in effective)
    history_uncertainty_factor = 0.75 if observation_count == 0 else 0.85 if observation_count == 1 else 0.90
    provisional_confidence = min(cfg["provisional_confidence_cap"], anchor_confidence * history_uncertainty_factor)
    return {
        **common,
        "status": "provisional",
        "status_label": "暫估模型／歷史資料不足",
        "anchors": anchors,
        "anchor_weights": normalized_weights,
        "provisional": {
            "base_pb": provisional_pb,
            "spread": provisional_spread,
            "bear_pb": bear_pb,
            "bull_pb": bull_pb,
            "bear_value": adjusted_bps * bear_pb,
            "base_value": adjusted_bps * provisional_pb,
            "bull_value": adjusted_bps * bull_pb,
            "confidence": provisional_confidence,
            "confidence_cap": cfg["provisional_confidence_cap"],
            "uncertainty_multiplier": uncertainty_multiplier,
        },
        "fair_pb": provisional_pb,
        "fair_value": adjusted_bps * provisional_pb,
        "bear_pb": bear_pb,
        "bull_pb": bull_pb,
        "confidence": "中低" if provisional_confidence >= 0.50 else "低",
        "confidence_score": provisional_confidence,
        "included_in_expanded_composite": True,
        "included_in_primary_composite": False,
        "reason": "Insufficient comparable adjusted P/B history; provisional anchors used",
        "warning": "由於尚未累積足夠可比較的歷史 Adjusted P/B 資料，此估值屬暫估模型，可信度低於正式歷史估值模型。Current Adjusted P/B 僅用於市場比較，沒有進入合理倍數計算。",
    }


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
    traditional_model = {
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
        }
    adjusted_model = calculate_adjusted_pb_layer(adjusted_bps, current_price, traditional_model, forecast, cfg)
    return {
        "traditional": traditional_model,
        "adjusted": adjusted_model,
        "bps_scenarios": {key: round(value, 2) for key, value in bps_scenarios.items()},
        "pb_scenarios": {key: round(value, 3) for key, value in pb_scenarios.items()},
    }
