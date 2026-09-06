from __future__ import annotations

from .pe_model import fair_pe
from .pb_model import calculate_pb_model
from .valuation_heat import calculate_valuation_heat
from .sustainable_pb import calculate_sustainable_pb, compare_independent_valuations


def classify(price_to_fair: float) -> str:
    if price_to_fair <= 0.85:
        return "非常有吸引力"
    if price_to_fair <= 0.95:
        return "有吸引力"
    if price_to_fair <= 1.05:
        return "合理"
    if price_to_fair <= 1.15:
        return "略為昂貴"
    return "昂貴"


def confidence(pe: dict) -> str:
    if pe["confidence_score"] >= 0.75:
        return "高"
    if pe["confidence_score"] >= 0.50:
        return "中"
    return "低"


def calculate(snapshot: dict, history: list[dict], forecast: dict, overrides: dict) -> dict:
    default_base = forecast["analyst_eps_median"]
    base_eps = overrides.get("forecast_eps") or default_base
    if overrides.get("forecast_eps") is not None:
        ratio = base_eps / default_base
        bear_eps = overrides.get("forecast_eps_low") or forecast["analyst_eps_low"] * ratio
        bull_eps = overrides.get("forecast_eps_high") or forecast["analyst_eps_high"] * ratio
        eps_source = "分析師 Low／Median／High，依手動 Median 等比例調整"
    else:
        bear_eps = overrides.get("forecast_eps_low") or forecast["analyst_eps_low"]
        bull_eps = overrides.get("forecast_eps_high") or forecast["analyst_eps_high"]
        eps_source = "公告口徑 EPS 與歷史趨勢三情境" if forecast.get("data_method") else "分析師 EPS Low／Median／High"

    bps = overrides.get("forecast_bps") or forecast["forecast_bps"]
    pe_weights = (
        overrides.get("regression_weight", 0.25),
        overrides.get("recent_weight", 0.45),
        overrides.get("historical_weight", 0.30),
    )
    pe = fair_pe(
        history,
        base_eps,
        pe_weights,
        current_regime_observations=forecast.get("recent_quarterly_pe"),
        current_regime_source=forecast.get("recent_pe_source"),
        fundamental_flags=forecast.get("fundamental_flags"),
        accounting_regime_change=forecast.get("accounting_regime_change", False),
    )
    spread = overrides.get("pe_spread")
    spread = pe["spread"] if spread is None else spread
    base_pe = pe["fair_pe"]
    if overrides.get("pe_spread") is None:
        bear_pe, bull_pe = pe["bear_pe"], pe["bull_pe"]
    else:
        p10, p90 = pe["percentile_bounds"]
        bear_pe = max(base_pe - spread, p10 * 0.90)
        bull_pe = min(base_pe + spread, p90 * 1.10)

    pb = calculate_pb_model(history, snapshot["current_price"], {**forecast, "forecast_bps": bps})
    capital_efficiency = calculate_sustainable_pb(history, snapshot["current_price"], bps, forecast)
    if capital_efficiency.get("fair_pb") is None:
        raise ValueError("Sustainable P/B model lacks basis-consistent data")
    fundamental_fair_pb = capital_efficiency["fair_pb"]
    peer_regime = forecast.get("sector_peer_regime")
    peer_factor = float(peer_regime["adjustment_factor"]) if peer_regime and peer_regime.get("confirmed") else 1.0
    fair_pb = fundamental_fair_pb * peer_factor
    capital_efficiency["fundamental_fair_pb"] = fundamental_fair_pb
    capital_efficiency["sector_peer_regime"] = peer_regime
    capital_efficiency["peer_adjustment_factor"] = peer_factor
    capital_efficiency["fair_pb"] = fair_pb
    capital_efficiency["fair_value"] = bps * fair_pb
    capital_efficiency["sensitivity_pb"] = {name: value * peer_factor for name, value in capital_efficiency["sensitivity_pb"].items()}
    capital_confidence_score = 0.65 if capital_efficiency["confidence"] == "Medium" else 0.45
    traditional = pb["traditional"]
    traditional.update({
        "final_fair_pb": fair_pb,
        "base_pb": fair_pb,
        "bear_pb": capital_efficiency["sensitivity_pb"]["bear"],
        "bull_pb": capital_efficiency["sensitivity_pb"]["bull"],
        "spread": capital_efficiency["sensitivity_pb"]["bull"] - fair_pb,
        "premium_to_final_pct": (capital_efficiency["current_pb"] / fair_pb - 1) * 100,
        "required_bps": snapshot["current_price"] / fair_pb,
        "confidence_score": capital_confidence_score,
        "confidence": capital_efficiency["confidence"],
        "valuation_basis": "sustainable_roe",
    })
    pb["pb_scenarios"] = {key: round(value, 3) for key, value in capital_efficiency["sensitivity_pb"].items()}
    traditional["target_prices"] = {
        name: pb["bps_scenarios"][name] * capital_efficiency["sensitivity_pb"][name]
        for name in ("bear", "base", "bull")
    }
    traditional["valuation_matrix"] = [
        {"scenario": row_name, "bps": pb["bps_scenarios"][row_name], "prices": {col_name: round(pb["bps_scenarios"][row_name] * multiple, 2) for col_name, multiple in capital_efficiency["sensitivity_pb"].items()}}
        for row_name in ("bear", "base", "bull")
    ]
    pb["capital_efficiency"] = capital_efficiency
    pe_price = base_eps * base_pe
    pb_price = bps * fair_pb
    if overrides.get("weights_are_final"):
        pe_weight = float(overrides.get("pe_weight", 0.50))
        pb_weight = 1 - pe_weight
    else:
        pe_weight = overrides.get("pe_weight", 0.50) * pe["confidence_score"]
        pb_weight = overrides.get("pb_weight", 0.50) * pb["traditional"]["confidence_score"]
        total = pe_weight + pb_weight
        pe_weight, pb_weight = pe_weight / total, pb_weight / total
    fair_value = pe_price * pe_weight + pb_price * pb_weight
    cross_validation = compare_independent_valuations(pe_price, pb_price)

    adjusted = pb["adjusted"]
    adjusted_family_cap = 0.30 if adjusted["status"] == "provisional" else 0.40
    adjusted_family_raw = adjusted_family_cap * adjusted["confidence_score"]
    traditional_family_raw = (1 - adjusted_family_cap) * pb["traditional"]["confidence_score"]
    pb_family_total = traditional_family_raw + adjusted_family_raw
    adjusted_family_weight = adjusted_family_raw / pb_family_total if pb_family_total else 0
    if pb_weight > 0:
        adjusted_family_weight = min(adjusted_family_weight, 0.15 / pb_weight)
    traditional_family_weight = 1 - adjusted_family_weight
    expanded_pb_value = pb_price * traditional_family_weight + adjusted["fair_value"] * adjusted_family_weight
    expanded_fair_value = pe_price * pe_weight + expanded_pb_value * pb_weight
    expanded_weights = {
        "pe": pe_weight,
        "traditional_pb": pb_weight * traditional_family_weight,
        "adjusted_pb": pb_weight * adjusted_family_weight,
    }
    rounded_expanded_weights = {
        "pe": round(expanded_weights["pe"], 3),
        "traditional_pb": round(expanded_weights["traditional_pb"], 3),
    }
    rounded_expanded_weights["adjusted_pb"] = round(1 - rounded_expanded_weights["pe"] - rounded_expanded_weights["traditional_pb"], 3)

    bear_price = bear_eps * bear_pe
    base_price = base_eps * base_pe
    bull_price = bull_eps * bull_pe
    pe_scenario_prices = {"bear": bear_price, "base": base_price, "bull": bull_price}
    pb_scenario_prices = pb["traditional"]["target_prices"]
    composite_scenario_prices = {
        name: pe_scenario_prices[name] * pe_weight + pb_scenario_prices[name] * pb_weight
        for name in ("bear", "base", "bull")
    }
    current_price = snapshot["current_price"]
    upside = (fair_value / current_price - 1) * 100
    price_to_fair = current_price / fair_value
    required_eps = current_price / base_pe
    current_pb = current_price / bps
    valuation_heat = calculate_valuation_heat(
        current_price=current_price,
        base_forecast_eps=base_eps,
        historical_fair_pe=pe["historical_fair_pe"],
        final_fair_pe=base_pe,
        current_regime_pe=pe["current_regime_pe"],
        forecast=forecast,
        history=history,
    )

    eps_rows = [("bear", bear_eps), ("base", base_eps), ("bull", bull_eps)]
    pe_cols = [("bear", bear_pe), ("base", base_pe), ("bull", bull_pe)]
    matrix = [
        {
            "scenario": eps_name,
            "eps": round(eps_value, 2),
            "prices": {pe_name: round(eps_value * pe_value, 2) for pe_name, pe_value in pe_cols},
        }
        for eps_name, eps_value in eps_rows
    ]

    return {
        "ticker": snapshot["ticker"],
        "company_name": snapshot["company_name"],
        "current_price": current_price,
        "fair_pe": round(base_pe, 2),
        "pe_target_price": round(pe_price, 2),
        "fair_pb": fair_pb,
        "pb_target_price": round(pb_price, 2),
        "fair_value": round(fair_value, 2),
        "composite": {
            "primary_fair_value": round(fair_value, 2),
            "includes_adjusted_pb": False,
            "label": "可驗證資料基礎合理價",
            "basis": "使用 P/E 與 Sustainable ROE P/B；大型金融同業 Regime 確認後，僅對 P/B 三情境作受限校準",
            "expanded_fair_value": round(expanded_fair_value, 2),
            "expanded_pb_family_value": round(expanded_pb_value, 2),
            "expanded_includes_provisional": adjusted["status"] == "provisional",
            "expanded_weights": rounded_expanded_weights,
        },
        "bear_value": round(composite_scenario_prices["bear"], 2),
        "bull_value": round(composite_scenario_prices["bull"], 2),
        "upside_pct": round(upside, 2),
        "implied_forward_pe": round(current_price / base_eps, 2),
        "classification": classify(price_to_fair),
        "confidence": confidence(pe),
        "valuation_heat": valuation_heat,
        "capital_efficiency": capital_efficiency,
        "cross_validation": cross_validation,
        "historical": history,
        "assumptions": {
            "forecast_eps": round(base_eps, 2),
            "forecast_eps_low": round(bear_eps, 2),
            "forecast_eps_high": round(bull_eps, 2),
            "eps_source": eps_source,
            "forecast_method": "依最新公告口徑 EPS 與近年趨勢、波動度自動產生 Low／Base／High" if forecast.get("data_method") else "優先採分析師 Low／Median／High，不以固定百分比製造情境",
            "forecast_bps": bps,
            "bps_method": f"截至 {forecast['as_of']} 的市場公告口徑 BPS（同日股價÷P/B）；BPS 為期末存量，不作年化" if forecast.get("data_method") else "2026 上半年普通股每股淨值 83.7；BPS 為期末存量，不作年化",
            "adjusted_bps_reference": forecast["adjusted_bps"],
            "current_pb": round(current_pb, 2),
            "adjusted_current_pb": round(pb["adjusted"]["current_pb"], 2),
            "pb_model": pb,
            "regression_pe": round(pe["regression_pe"], 2),
            "recent_pe": round(pe["recent_pe"], 2),
            "historical_median_pe": round(pe["historical_median_pe"], 2),
            "historical_mean_pe": round(pe["historical_mean_pe"], 2),
            "pe_percentile_bounds": [round(v, 2) for v in pe["percentile_bounds"]],
            "pe_spread": spread,
            "pe_mad": round(pe["pe_mad"], 2),
            "pe_volatility": round(pe["pe_volatility"], 2),
            "eps_pe_correlation": round(pe["correlation"], 3),
            "regression_r2": round(pe["regression_r2"], 3),
            "rerating_ratio": round(pe["rerating_ratio"], 3),
            "rerating_label": pe["rerating_label"],
            "recent_5y_pe": round(pe["recent_5y_pe"], 2),
            "recent_pe_source": pe["recent_pe_source"],
            "base_pe_before_rerating": round(pe["base_before_rerating"], 2),
            "base_pe_after_rerating": round(pe["base_after_rerating"], 2),
            "historical_fair_pe": round(pe["historical_fair_pe"], 2),
            "current_regime_pe": round(pe["current_regime_pe"], 2) if pe["current_regime_pe"] is not None else None,
            "premium_to_historical_pe_pct": round((current_price / base_eps / pe["historical_fair_pe"] - 1) * 100, 2),
            "confidence_score": round(pe["confidence_score"], 3),
            "rerating": {
                "historical_pe_median": round(pe["historical_median_pe"], 2),
                "recent_pe_median": round(pe["recent_pe"], 2),
                "rerating_ratio": round(pe["regime_ratio"], 3),
                "direction": pe["rerating_direction"],
                "label": pe["rerating_label"],
                "persistence_count": pe["persistence_count"],
                "persistence_score": round(pe["persistence_score"], 3),
                "strength": round(pe["rerating_strength"], 3),
                "source": pe["current_regime_source"],
                "observation_count": pe["current_regime_count"],
                "current_regime_pe": None if pe["current_regime_pe"] is None else round(pe["current_regime_pe"], 2),
                "current_regime_mean": None if pe["current_regime_mean"] is None else round(pe["current_regime_mean"], 2),
                "current_regime_mad": None if pe["current_regime_mad"] is None else round(pe["current_regime_mad"], 2),
                "current_regime_p25": None if pe["current_regime_p25"] is None else round(pe["current_regime_p25"], 2),
                "current_regime_p75": None if pe["current_regime_p75"] is None else round(pe["current_regime_p75"], 2),
                "fundamental_score": round(pe["fundamental_confirmation_score"], 2),
                "fundamental_confirmation": pe["fundamental_confirmation"],
                "fundamental_checks": pe["fundamental_checks"],
                "accounting_regime_change": pe["accounting_regime_change"],
                "historical_model_weights": {key: round(value, 3) for key, value in pe["historical_weights"].items()},
                "raw_regime_weight": round(pe["raw_regime_weight"], 3),
                "effective_regime_weight": round(pe["effective_regime_weight"], 3),
                "historical_layer_weight": round(pe["historical_layer_weight"], 3),
                "weight_shift": round(pe["weight_shift"], 3),
                "regime_bound": None if pe["regime_bound"] is None else round(pe["regime_bound"], 2),
                "regime_bound_type": pe["regime_bound_type"],
                "confirmed": pe["structural_rerating_confirmed"],
            },
            "regression_formula": f"P/E = {pe['regression_intercept']:.2f} + ({pe['regression_slope']:.2f} × EPS)",
            "pe_reference_weights": [round(v, 3) for v in pe["normalized_weights"]],
            "model_weights": {"pe": round(pe_weight, 3), "pb": round(pb_weight, 3)},
            "scenarios": {
                name: {
                    "eps": round(eps, 2),
                    "pe": round(pe_multiple, 2),
                    "bps": pb["bps_scenarios"][name],
                    "pb": pb["pb_scenarios"][name],
                    "pe_value": round(pe_scenario_prices[name], 2),
                    "pb_value": round(pb_scenario_prices[name], 2),
                    "composite_value": round(composite_scenario_prices[name], 2),
                }
                for name, eps, pe_multiple in (
                    ("bear", bear_eps, bear_pe),
                    ("base", base_eps, base_pe),
                    ("bull", bull_eps, bull_pe),
                )
            },
            "valuation_matrix": matrix,
            "required_eps": round(required_eps, 2),
            "premium_to_fair_pe_pct": round((current_price / base_eps / base_pe - 1) * 100, 2),
            "safety_margin_pct": round((1 - current_price / fair_value) * 100, 2),
            "eps_basis": "最新公告口徑 EPS 經歷史趨勢正常化（可手動覆寫中位數）" if forecast.get("data_method") else "2026 年分析師預估 EPS（可手動覆寫中位數）",
        },
        "source_notes": ([
            {"name": f"{snapshot.get('price_source', '固定測試資料')} 股價", "as_of": snapshot["as_of"], "note": f"參考股價 NT${current_price:.2f}"},
            {"name": "免費公開資料估值管線", "as_of": forecast["as_of"], "note": forecast["data_method"]},
        ] if forecast.get("data_method") else [
            {"name": "富邦金控股價資訊", "as_of": snapshot["as_of"], "note": "參考股價 NT$150.50"},
            {"name": "Golden test fixture", "as_of": forecast["as_of"], "note": "歷史 EPS、P/E、BPS 與預估資料用於演算法驗證"},
        ]),
        "model_version": "tw-valuation-mvp-2.8",
    }
