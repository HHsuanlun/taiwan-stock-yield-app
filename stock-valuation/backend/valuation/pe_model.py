from __future__ import annotations

import math
from statistics import mean, median, pstdev


DEFAULT_PE_CONFIG = {
    "regression_full_r2": 0.50,
    "regime_threshold": 0.10,
    "strength_full_scale": 0.30,
    "min_regime_weight": 0.20,
    "max_regime_weight": 0.70,
    "accounting_change_max_weight": 0.80,
    "minimum_persistence": 0.50,
    "partial_persistence": 0.67,
    "partial_weight_cap": 0.40,
}


def clamp(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * p
    low, high = math.floor(index), math.ceil(index)
    if low == high:
        return ordered[low]
    return ordered[low] * (high - index) + ordered[high] * (index - low)


def linear_reference(xs: list[float], ys: list[float], target_x: float) -> tuple[float, float, float]:
    x_bar, y_bar = mean(xs), mean(ys)
    variance = sum((x - x_bar) ** 2 for x in xs)
    slope = 0.0 if variance == 0 else sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys)) / variance
    intercept = y_bar - slope * x_bar
    return intercept + slope * target_x, intercept, slope


def correlation(xs: list[float], ys: list[float]) -> float:
    x_bar, y_bar = mean(xs), mean(ys)
    numerator = sum((x - x_bar) * (y - y_bar) for x, y in zip(xs, ys))
    x_var = sum((x - x_bar) ** 2 for x in xs)
    y_var = sum((y - y_bar) ** 2 for y in ys)
    return 0.0 if x_var == 0 or y_var == 0 else numerator / math.sqrt(x_var * y_var)


def reliable_historical_weights(weights: tuple[float, float, float], r_squared: float, config: dict) -> dict:
    reg_base, recent_base, hist_base = weights
    total = reg_base + recent_base + hist_base
    reg_base, recent_base, hist_base = reg_base / total, recent_base / total, hist_base / total
    effective_reg = reg_base * clamp(r_squared / config["regression_full_r2"], 0, 1)
    unused = reg_base - effective_reg
    return {"historical": hist_base + unused * 0.30, "recent": recent_base + unused * 0.70, "regression": effective_reg}


def fundamental_score(flags: dict | None) -> float:
    if not flags:
        return 0.0
    keys = ("eps_stable_or_improving", "bps_improving", "roe_stable_or_improving", "dividend_stable_or_improving")
    return sum(0.25 for key in keys if flags.get(key))


def fair_pe(
    history: list[dict],
    forecast_eps: float,
    weights: tuple[float, float, float],
    config: dict | None = None,
    current_regime_observations: list[float] | None = None,
    current_regime_source: str | None = None,
    fundamental_flags: dict | None = None,
    accounting_regime_change: bool = False,
) -> dict:
    cfg = {**DEFAULT_PE_CONFIG, **(config or {})}
    usable = [row for row in history if row.get("eps") is not None and row.get("pe") is not None][-10:]
    if len(usable) < 3:
        raise ValueError("至少需要 3 筆 EPS 與 P/E 歷史資料")
    eps_values = [float(row["eps"]) for row in usable]
    pe_values = [float(row["pe"]) for row in usable]
    regression, intercept, slope = linear_reference(eps_values, pe_values, forecast_eps)
    corr = correlation(eps_values, pe_values)
    r_squared = corr**2
    historical_median = median(pe_values)
    recent_median = median(pe_values[-3:])
    hist_weights = reliable_historical_weights(weights, r_squared, cfg)
    historical_fair = (
        historical_median * hist_weights["historical"]
        + recent_median * hist_weights["recent"]
        + regression * hist_weights["regression"]
    )

    regime_values = [float(value) for value in (current_regime_observations or []) if value and value > 0]
    regime_available = len(regime_values) >= 4
    regime_median = regime_mean = regime_mad = regime_p25 = regime_p75 = regime_p90 = None
    regime_ratio = persistence = strength = raw_weight = effective_weight = 0.0
    direction = "unavailable"
    if regime_available:
        p10, regime_p90 = percentile(regime_values, 0.10), percentile(regime_values, 0.90)
        winsorized = [clamp(value, p10, regime_p90) for value in regime_values]
        regime_median, regime_mean = median(winsorized), mean(winsorized)
        regime_mad = median([abs(value - regime_median) for value in winsorized])
        regime_p25, regime_p75 = percentile(winsorized, 0.25), percentile(winsorized, 0.75)
        regime_ratio = regime_median / historical_fair
        band = cfg["regime_threshold"]
        if regime_ratio > 1 + band:
            direction = "positive"
            persistent_count = sum(value > historical_fair * (1 + band) for value in regime_values)
        elif regime_ratio < 1 - band:
            direction = "negative"
            persistent_count = sum(value < historical_fair * (1 - band) for value in regime_values)
        else:
            direction, persistent_count = "none", 0
        persistence = persistent_count / len(regime_values)
        strength = abs(regime_ratio - 1) * persistence
        if direction != "none" and persistence >= cfg["minimum_persistence"]:
            max_weight = cfg["accounting_change_max_weight"] if accounting_regime_change else cfg["max_regime_weight"]
            normalized_strength = clamp(strength / cfg["strength_full_scale"], 0, 1)
            raw_weight = cfg["min_regime_weight"] + normalized_strength * (max_weight - cfg["min_regime_weight"])
            if persistence < cfg["partial_persistence"]:
                raw_weight = min(raw_weight, cfg["partial_weight_cap"])
            score = fundamental_score(fundamental_flags)
            effective_weight = raw_weight * (0.5 + 0.5 * score)

    final_base = historical_fair * (1 - effective_weight) + (regime_median or historical_fair) * effective_weight
    historical_mad = median([abs(value - historical_median) for value in pe_values])
    spread = clamp(0.8 * historical_mad, 0.75, 2.0)
    historical_p10, historical_p90 = percentile(pe_values, 0.10), percentile(pe_values, 0.90)
    lower_bound = historical_p10 * 0.90
    upper_bound = historical_p90 * 1.10
    rerating_confirmed = effective_weight > 0
    if rerating_confirmed and regime_p90 is not None:
        upper_bound = max(upper_bound, regime_p90 * 1.05)
    bear, bull = max(final_base - spread, lower_bound), min(final_base + spread, upper_bound)

    hist_score = 1.0 if len(usable) >= 10 else 0.7 if len(usable) >= 5 else 0.4
    regression_score = clamp(r_squared / 0.50, 0, 1)
    regime_score = 1.0 if len(regime_values) >= 8 else 0.7 if len(regime_values) >= 4 else 0.4
    f_score = fundamental_score(fundamental_flags)
    confidence_score = 0.25 * hist_score + 0.15 * regression_score + 0.25 * regime_score + 0.20 * persistence + 0.15 * f_score

    return {
        "fair_pe": final_base,
        "historical_fair_pe": historical_fair,
        "base_before_rerating": historical_fair,
        "base_after_rerating": final_base,
        "bear_pe": bear,
        "bull_pe": bull,
        "spread": spread,
        "pe_mad": historical_mad,
        "pe_volatility": pstdev(pe_values),
        "regression_pe": regression,
        "recent_pe": recent_median,
        "recent_5y_pe": median(pe_values[-5:]),
        "recent_pe_source": "最近 3 年年度 P/E 中位數",
        "historical_median_pe": historical_median,
        "historical_mean_pe": mean(pe_values),
        "percentile_bounds": [historical_p10, historical_p90],
        "regression_intercept": intercept,
        "regression_slope": slope,
        "correlation": corr,
        "regression_r2": r_squared,
        "normalized_weights": [hist_weights["regression"], hist_weights["recent"], hist_weights["historical"]],
        "history_count": len(usable),
        "current_regime_available": regime_available,
        "current_regime_source": current_regime_source if regime_available else None,
        "current_regime_count": len(regime_values),
        "current_regime_pe": regime_median,
        "current_regime_mean": regime_mean,
        "current_regime_mad": regime_mad,
        "current_regime_p25": regime_p25,
        "current_regime_p75": regime_p75,
        "regime_ratio": regime_ratio,
        "rerating_ratio": regime_ratio or 1.0,
        "rerating_direction": direction,
        "rerating_label": {"positive": "正向結構性重估", "negative": "負向結構性重估", "none": "無明確結構性重估", "unavailable": "Current regime 資料不足"}[direction],
        "persistence_count": round(persistence * len(regime_values)),
        "persistence_score": persistence,
        "rerating_strength": strength,
        "fundamental_confirmation_score": f_score,
        "fundamental_confirmation": f_score >= 0.50,
        "fundamental_checks": fundamental_flags or {},
        "accounting_regime_change": accounting_regime_change,
        "historical_weights": hist_weights,
        "base_weights": hist_weights,
        "effective_weights": hist_weights,
        "raw_regime_weight": raw_weight,
        "effective_regime_weight": effective_weight,
        "historical_layer_weight": 1 - effective_weight,
        "weight_shift": effective_weight,
        "regime_bound": None,
        "regime_bound_type": None,
        "structural_rerating_confirmed": rerating_confirmed,
        "confidence_score": confidence_score,
        "config": cfg,
    }
