import unittest

from backend.data.providers import FixtureProvider
from backend.valuation.pe_model import DEFAULT_PE_CONFIG, fair_pe
from backend.valuation.pb_model import calculate_pb_model
from backend.valuation.valuation_engine import calculate, classify


def fixture_result(**overrides):
    provider = FixtureProvider()
    return calculate(provider.get_snapshot("2881"), provider.get_history("2881"), provider.get_forecasts("2881"), overrides)


class Valuation2881Tests(unittest.TestCase):
    def test_complete_2881_valuation(self):
        result = fixture_result()
        self.assertEqual(result["ticker"], "2881")
        self.assertEqual(result["current_price"], 150.50)
        self.assertLess(result["bear_value"], result["pe_target_price"])
        self.assertLess(result["pe_target_price"], result["bull_value"])
        self.assertGreater(result["pe_target_price"], 0)
        self.assertEqual(result["pb_target_price"], round(result["fair_pb"] * result["assumptions"]["forecast_bps"], 2))
        self.assertEqual(len(result["historical"]), 10)
        self.assertIn("regression_pe", result["assumptions"])

    def test_manual_eps_override_recalculates_all_pe_outputs(self):
        baseline = fixture_result()
        changed = fixture_result(forecast_eps=13.0)
        self.assertLess(changed["implied_forward_pe"], baseline["implied_forward_pe"])
        self.assertNotEqual(changed["pe_target_price"], baseline["pe_target_price"])
        self.assertNotEqual(changed["fair_value"], baseline["fair_value"])

    def test_default_eps_uses_analyst_low_median_high(self):
        result = fixture_result()
        self.assertEqual(result["assumptions"]["forecast_eps_low"], 9.94)
        self.assertEqual(result["assumptions"]["forecast_eps"], 10.95)
        self.assertEqual(result["assumptions"]["forecast_eps_high"], 11.86)

    def test_default_bps_uses_reported_half_year_value_without_annualizing(self):
        result = fixture_result()
        self.assertEqual(result["assumptions"]["forecast_bps"], 83.7)
        self.assertEqual(result["assumptions"]["adjusted_bps_reference"], 109.3)

    def test_scenarios_expose_eps_and_pe_inputs(self):
        scenarios = fixture_result()["assumptions"]["scenarios"]
        self.assertLess(scenarios["bear"]["eps"], scenarios["base"]["eps"])
        self.assertLess(scenarios["bear"]["pe"], scenarios["base"]["pe"])
        self.assertGreater(scenarios["bull"]["eps"], scenarios["base"]["eps"])
        self.assertGreater(scenarios["bull"]["pe"], scenarios["base"]["pe"])

    def test_matrix_and_reverse_valuation_are_reproducible(self):
        result = fixture_result()
        assumptions = result["assumptions"]
        self.assertEqual(len(assumptions["valuation_matrix"]), 3)
        center = assumptions["valuation_matrix"][1]["prices"]["base"]
        self.assertEqual(center, result["pe_target_price"])
        self.assertAlmostEqual(assumptions["required_eps"] * result["fair_pe"], result["current_price"], delta=0.1)

    def test_pe_scenarios_use_mad_and_percentile_breakout_bounds(self):
        provider = FixtureProvider()
        result = fair_pe(provider.get_history("2881"), 10.95, (0.25, 0.45, 0.30))
        p10, p90 = result["percentile_bounds"]
        self.assertGreaterEqual(result["spread"], 0.75)
        self.assertLessEqual(result["spread"], 2.0)
        self.assertGreaterEqual(result["bear_pe"], p10 * 0.90)
        self.assertLessEqual(result["bull_pe"], p90 * 1.10)

    def test_regression_reliability_adjusts_and_preserves_weight_total(self):
        provider = FixtureProvider()
        result = fair_pe(provider.get_history("2881"), 10.95, (0.25, 0.45, 0.30))
        self.assertAlmostEqual(sum(result["normalized_weights"]), 1.0)
        self.assertLessEqual(result["normalized_weights"][0], 0.25)
        self.assertAlmostEqual(result["regression_r2"], result["correlation"] ** 2)

    def test_positive_rerating_increases_current_regime_weight(self):
        result = fixture_result()["assumptions"]["rerating"]
        self.assertEqual(result["direction"], "positive")
        self.assertTrue(result["confirmed"])
        self.assertGreater(result["effective_regime_weight"], 0)

    def test_historical_fair_pe_unchanged(self):
        result = fixture_result()["assumptions"]
        self.assertAlmostEqual(result["historical_fair_pe"], 9.96, places=2)

    def test_no_rerating_without_persistence(self):
        provider = FixtureProvider()
        result = fair_pe(provider.get_history("2881"), 10.95, (0.25, 0.45, 0.30), current_regime_observations=[9.8, 9.9, 10.0, 14.0])
        self.assertEqual(result["effective_regime_weight"], 0)
        self.assertEqual(result["fair_pe"], result["historical_fair_pe"])

    def test_no_price_chasing(self):
        provider = FixtureProvider()
        forecast = provider.get_forecasts("2881")
        first = calculate(provider.get_snapshot("2881"), provider.get_history("2881"), forecast, {})
        expensive_snapshot = {**provider.get_snapshot("2881"), "current_price": 300.0}
        second = calculate(expensive_snapshot, provider.get_history("2881"), forecast, {})
        self.assertEqual(first["fair_pe"], second["fair_pe"])

    def test_strong_fundamentals_allow_more_rerating_than_weak_fundamentals(self):
        provider = FixtureProvider()
        args = (provider.get_history("2881"), 10.95, (0.25, 0.45, 0.30))
        regime = [12.0, 12.3, 12.5, 12.7, 13.0, 13.2, 13.4, 13.6]
        strong = fair_pe(*args, current_regime_observations=regime, fundamental_flags={"eps_stable_or_improving": True, "bps_improving": True, "roe_stable_or_improving": True, "dividend_stable_or_improving": True})
        weak = fair_pe(*args, current_regime_observations=regime, fundamental_flags={})
        self.assertGreater(strong["effective_regime_weight"], weak["effective_regime_weight"])

    def test_missing_regime_data_falls_back_to_historical_model(self):
        provider = FixtureProvider()
        result = fair_pe(provider.get_history("2881"), 10.95, (0.25, 0.45, 0.30))
        self.assertFalse(result["current_regime_available"])
        self.assertEqual(result["fair_pe"], result["historical_fair_pe"])

    def test_bear_base_bull_spread(self):
        result = fixture_result()
        scenarios, spread = result["assumptions"]["scenarios"], result["assumptions"]["pe_spread"]
        self.assertAlmostEqual(scenarios["bear"]["pe"], scenarios["base"]["pe"] - spread, places=2)
        self.assertAlmostEqual(scenarios["bull"]["pe"], scenarios["base"]["pe"] + spread, places=2)

    def test_layer_weights_sum_to_one(self):
        result = fixture_result()["assumptions"]["rerating"]
        self.assertAlmostEqual(result["historical_layer_weight"] + result["effective_regime_weight"], 1.0)

    def test_pb_model_is_data_driven_and_reproducible(self):
        provider = FixtureProvider()
        result = calculate_pb_model(provider.get_history("2881"), 150.5, provider.get_forecasts("2881"))["traditional"]
        self.assertAlmostEqual(result["historical_median"], 1.18)
        self.assertAlmostEqual(result["current_regime_pb"], 1.555)
        self.assertAlmostEqual(result["historical_weight"] + result["regime_weight"], 1.0)
        self.assertAlmostEqual(result["target_prices"]["base"], 83.7 * result["final_fair_pb"])

    def test_pb_model_does_not_chase_current_price(self):
        provider = FixtureProvider()
        first = calculate_pb_model(provider.get_history("2881"), 150.5, provider.get_forecasts("2881"))
        second = calculate_pb_model(provider.get_history("2881"), 300.0, provider.get_forecasts("2881"))
        self.assertEqual(first["traditional"]["final_fair_pb"], second["traditional"]["final_fair_pb"])

    def test_adjusted_bps_is_not_multiplied_by_traditional_pb(self):
        provider = FixtureProvider()
        adjusted = calculate_pb_model(provider.get_history("2881"), 150.5, provider.get_forecasts("2881"))["adjusted"]
        self.assertIsNone(adjusted["final_fair_pb"])
        self.assertIsNone(adjusted["target_price"])
        self.assertEqual(adjusted["confidence"], "低")
        self.assertEqual(adjusted["status"], "reference_only")
        self.assertEqual(adjusted["historical_observation_count"], 1)
        self.assertIsNone(adjusted["fair_value"])
        self.assertFalse(adjusted["included_in_composite"])

    def test_primary_composite_excludes_adjusted_pb(self):
        result = fixture_result()
        self.assertEqual(result["composite"]["primary_fair_value"], result["fair_value"])
        self.assertFalse(result["composite"]["includes_adjusted_pb"])
        adjusted = result["assumptions"]["pb_model"]["adjusted"]
        self.assertAlmostEqual(adjusted["discount_vs_traditional_pct"], -23.33, delta=0.1)

    def test_pb_matrix_and_spread(self):
        provider = FixtureProvider()
        model = calculate_pb_model(provider.get_history("2881"), 150.5, provider.get_forecasts("2881"))
        traditional = model["traditional"]
        self.assertEqual(len(traditional["valuation_matrix"]), 3)
        self.assertGreaterEqual(traditional["spread"], 0.05)
        self.assertLessEqual(traditional["spread"], 0.30)
        self.assertAlmostEqual(traditional["bear_pb"], traditional["base_pb"] - traditional["spread"])
        self.assertAlmostEqual(traditional["bull_pb"], traditional["base_pb"] + traditional["spread"])

    def test_rerating_thresholds_are_configured_outside_calculation(self):
        self.assertEqual(DEFAULT_PE_CONFIG["regime_threshold"], 0.10)
        self.assertEqual(DEFAULT_PE_CONFIG["minimum_persistence"], 0.50)

    def test_classification_boundaries(self):
        self.assertEqual(classify(0.85), "非常有吸引力")
        self.assertEqual(classify(0.95), "有吸引力")
        self.assertEqual(classify(1.05), "合理")
        self.assertEqual(classify(1.15), "略為昂貴")
        self.assertEqual(classify(1.16), "昂貴")


if __name__ == "__main__":
    unittest.main()
