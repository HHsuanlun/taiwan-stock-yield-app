from __future__ import annotations

import math


DEFAULT_HEAT_CONFIG = {
    "ratio_thresholds": [
        (0.85, "Deep Discount"),
        (1.00, "Undervalued"),
        (1.15, "Fair / Normal"),
        (1.30, "Warm"),
        (1.50, "Hot"),
        (float("inf"), "Extremely Optimistic"),
    ],
    "score_thresholds": [
        (20, "Cheap"),
        (40, "Reasonable"),
        (60, "Elevated"),
        (75, "Hot"),
        (90, "Very Hot"),
        (101, "Extreme Expectations"),
    ],
    "weights": {"fair_pe_premium": 0.40, "required_eps_gap": 0.25, "catch_up_risk": 0.20, "multiple_expansion": 0.15},
    "fy2_catch_up_reduction": 25,
    "fy3_catch_up_reduction": 15,
    "multiple_expansion_penalties": [(0.80, 20), (0.60, 10)],
}


def _interpolate(value: float, points: list[tuple[float, float]]) -> float:
    if value <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if value <= x1:
            return y0 + (value - x0) / (x1 - x0) * (y1 - y0)
    return points[-1][1]


def _label(value: float, thresholds: list[tuple[float, str]]) -> str:
    return next(label for ceiling, label in thresholds if value < ceiling)


def calculate_valuation_heat(
    current_price: float,
    base_forecast_eps: float,
    historical_fair_pe: float,
    final_fair_pe: float,
    current_regime_pe: float | None,
    forecast: dict,
    history: list[dict],
    config: dict | None = None,
) -> dict:
    cfg = {**DEFAULT_HEAT_CONFIG, **(config or {})}
    forward_eps = {"fy1": base_forecast_eps}
    forward_eps.update({key: float(value) for key, value in forecast.get("forward_eps", {}).items() if value and key in {"fy2", "fy3"}})
    forward_pe = {key: current_price / eps for key, eps in forward_eps.items()}
    trailing_eps = forecast.get("ttm_eps")
    trailing_pe = current_price / trailing_eps if trailing_eps and trailing_eps > 0 else None
    overheat_ratio = forward_pe["fy1"] / final_fair_pe
    premium_historical = forward_pe["fy1"] / historical_fair_pe - 1
    premium_final = overheat_ratio - 1
    required_eps = current_price / final_fair_pe
    required_gap = required_eps / base_forecast_eps - 1

    growth = {
        "fy1_to_fy2": forward_eps["fy2"] / forward_eps["fy1"] - 1 if "fy2" in forward_eps else None,
        "fy2_to_fy3": forward_eps["fy3"] / forward_eps["fy2"] - 1 if "fy2" in forward_eps and "fy3" in forward_eps else None,
    }
    compression = forward_pe["fy1"] / forward_pe["fy3"] - 1 if "fy3" in forward_pe else None
    catch_up_score = None
    priced_in_horizon = "資料不足"
    catch_up_reduction = 0
    if "fy2" in forward_eps and required_eps <= forward_eps["fy2"]:
        priced_in_horizon = "約 1～2 年"
        catch_up_score = 1.0
        catch_up_reduction = cfg["fy2_catch_up_reduction"]
    elif "fy3" in forward_eps and required_eps <= forward_eps["fy3"]:
        priced_in_horizon = "約 2～3 年"
        catch_up_score = 0.75
        catch_up_reduction = cfg["fy3_catch_up_reduction"]
    elif "fy3" in forward_eps:
        priced_in_horizon = "三年預估仍未追上"
        catch_up_score = 0.0

    attribution = None
    expansion_penalty = 0
    baseline = forecast.get("price_attribution_baseline")
    if baseline and baseline.get("price") and baseline.get("eps"):
        current_eps = forecast.get("ttm_eps") or base_forecast_eps
        pe0 = baseline["price"] / baseline["eps"]
        pe1 = current_price / current_eps
        earnings_log = math.log(current_eps / baseline["eps"])
        multiple_log = math.log(pe1 / pe0)
        total_abs = abs(earnings_log) + abs(multiple_log)
        multiple_share = abs(multiple_log) / total_abs if total_abs else 0
        attribution = {"earnings_contribution": earnings_log, "multiple_contribution": multiple_log, "multiple_expansion_share": multiple_share}
        for threshold, penalty in cfg["multiple_expansion_penalties"]:
            if multiple_share > threshold:
                expansion_penalty = penalty
                break

    component_scores = {
        "fair_pe_premium": _interpolate(max(0, premium_final), [(0, 0), (0.15, 30), (0.30, 60), (0.50, 85), (0.75, 100)]),
        "required_eps_gap": _interpolate(max(0, required_gap), [(0, 0), (0.10, 30), (0.20, 60), (0.30, 80), (0.40, 100)]),
        "catch_up_risk": None if catch_up_score is None else 100 * (1 - catch_up_score),
        "multiple_expansion": None if attribution is None else 100 * attribution["multiple_expansion_share"],
    }
    available_weight = sum(cfg["weights"][key] for key, score in component_scores.items() if score is not None)
    base_score = sum(cfg["weights"][key] * score for key, score in component_scores.items() if score is not None) / available_weight
    heat_score = max(0, min(100, base_score - catch_up_reduction + expansion_penalty))
    analyst_target = forecast.get("analyst_target_price")
    analyst_implied_pe = analyst_target / base_forecast_eps if analyst_target else None

    if catch_up_score is None:
        conclusion = f"目前 Forward P/E 較模型合理 P/E 高 {premium_final * 100:.1f}%。公司 EPS 需達 {required_eps:.2f} 元，才能在合理倍數下支撐目前股價；因缺少 FY2／FY3 預估，暫時無法判斷成長消化期間。"
    elif catch_up_score > 0:
        conclusion = f"目前估值偏高，但未來 {priced_in_horizon} EPS 成長有機會部分消化目前估值溢價。"
    else:
        conclusion = "即使採用未來三年 EPS 預估，目前價格仍需依賴高於模型合理水準的 P/E 支撐。"

    return {
        "trailing_eps": trailing_eps,
        "trailing_pe": trailing_pe,
        "forward_eps": forward_eps,
        "forward_pe": forward_pe,
        "historical_fair_pe": historical_fair_pe,
        "final_fair_pe": final_fair_pe,
        "current_regime_pe": current_regime_pe,
        "pe_overheat_ratio": overheat_ratio,
        "ratio_label": _label(overheat_ratio, cfg["ratio_thresholds"]),
        "premium_to_historical": premium_historical,
        "premium_to_final_fair": premium_final,
        "required_eps": required_eps,
        "base_forecast_eps": base_forecast_eps,
        "required_eps_gap": required_gap,
        "forward_eps_growth": growth,
        "pe_compression_2y": compression,
        "earnings_catch_up_score": catch_up_score,
        "priced_in_horizon": priced_in_horizon,
        "price_attribution": attribution,
        "analyst_target_implied_pe": analyst_implied_pe,
        "analyst_optimism_ratio": analyst_implied_pe / final_fair_pe if analyst_implied_pe else None,
        "component_scores": component_scores,
        "available_score_weight": available_weight,
        "catch_up_reduction": catch_up_reduction,
        "multiple_expansion_penalty": expansion_penalty,
        "heat_score": round(heat_score),
        "heat_label": _label(heat_score, cfg["score_thresholds"]),
        "conclusion": conclusion,
        "data_limitations": [
            label for missing, label in (
                (trailing_pe is None, "TTM EPS"),
                ("fy2" not in forward_eps or "fy3" not in forward_eps, "FY2／FY3 EPS 預估"),
                (attribution is None, "股價與 EPS 基期資料"),
                (analyst_implied_pe is None, "分析師目標價"),
            ) if missing
        ],
    }
