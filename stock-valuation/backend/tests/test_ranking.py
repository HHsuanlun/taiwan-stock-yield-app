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

    def test_ranking_reports_failed_ticker_without_stale_placeholder(self):
        def loader(ticker):
            if ticker == "2881":
                raise ValueError("資料不足")
            return {"ticker": ticker, "company_name": "玉山金", "current_price": 30, "fair_value": 36, "upside_pct": 20, "classification": "便宜", "confidence": "中"}

        ranking = RankingService(loader, tickers=("2881", "2884"), cache_seconds=60).get()
        self.assertEqual(ranking["available"], 1)
        self.assertEqual(ranking["rows"][0]["ticker"], "2884")
        self.assertEqual(ranking["errors"][0]["ticker"], "2881")


if __name__ == "__main__":
    unittest.main()
