import unittest

from backend.ranking import RankingService


class RankingServiceTests(unittest.TestCase):
    def test_ranking_sorts_by_fair_value_upside_and_excludes_unspecified_tickers(self):
        values = {
            "2880": {"ticker": "2880", "company_name": "華南金", "current_price": 40, "fair_value": 36, "upside_pct": -10, "classification": "昂貴", "confidence": "中"},
            "2884": {"ticker": "2884", "company_name": "玉山金", "current_price": 30, "fair_value": 36, "upside_pct": 20, "classification": "便宜", "confidence": "中"},
            "2891": {"ticker": "2891", "company_name": "中信金", "current_price": 50, "fair_value": 50, "upside_pct": 0, "classification": "合理", "confidence": "高"},
        }
        ranking = RankingService(values.__getitem__, tickers=tuple(values), cache_seconds=60).get()
        self.assertEqual([row["ticker"] for row in ranking["rows"]], ["2884", "2891", "2880"])
        self.assertEqual([row["rank"] for row in ranking["rows"]], [1, 2, 3])
        self.assertEqual(ranking["available"], 3)
        self.assertEqual(ranking["total"], 3)
        self.assertEqual(ranking["shareholder_earnings_reference"]["ticker"], "2891")
        self.assertIn("正式 EPS", ranking["shareholder_earnings_reference"]["selection_basis"])

    def test_ranking_reports_failed_ticker_without_stale_placeholder(self):
        def loader(ticker):
            if ticker == "2881":
                raise ValueError("資料不足")
            return {"ticker": ticker, "company_name": "玉山金", "current_price": 30, "fair_value": 36, "upside_pct": 20, "classification": "便宜", "confidence": "中"}

        ranking = RankingService(loader, tickers=("2881", "2884"), cache_seconds=60).get()
        self.assertEqual(ranking["available"], 1)
        self.assertEqual(ranking["rows"][0]["ticker"], "2884")
        self.assertEqual(ranking["errors"][0]["ticker"], "2881")

    def test_shareholder_earnings_reference_uses_best_primary_gap_among_suitable_stocks(self):
        values = {
            "2881": {"ticker": "2881", "company_name": "富邦金", "current_price": 100, "fair_value": 110, "upside_pct": 10, "classification": "合理", "confidence": "中"},
            "2882": {"ticker": "2882", "company_name": "國泰金", "current_price": 60, "fair_value": 75, "upside_pct": 25, "classification": "便宜", "confidence": "中"},
            "2884": {"ticker": "2884", "company_name": "玉山金", "current_price": 30, "fair_value": 45, "upside_pct": 50, "classification": "便宜", "confidence": "中"},
        }
        ranking = RankingService(values.__getitem__, tickers=tuple(values), cache_seconds=60).get()
        reference = ranking["shareholder_earnings_reference"]
        self.assertEqual(reference["ticker"], "2882")
        self.assertEqual(reference["upside_pct"], 25.0)

    def test_securities_holding_can_join_reference_candidates(self):
        values = {
            "2884": {"ticker": "2884", "company_name": "玉山金", "current_price": 30, "fair_value": 45, "upside_pct": 50, "classification": "便宜", "confidence": "中"},
            "2885": {"ticker": "2885", "company_name": "元大金", "current_price": 40, "fair_value": 44, "upside_pct": 10, "classification": "合理", "confidence": "中"},
        }
        ranking = RankingService(values.__getitem__, tickers=tuple(values), cache_seconds=60).get()
        reference = ranking["shareholder_earnings_reference"]
        self.assertEqual(reference["ticker"], "2885")
        self.assertIn("證券型", reference["profile"])


if __name__ == "__main__":
    unittest.main()
