from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import pandas as pd

import screener.stocks_screener as stocks_screener


class CAC40UniverseTests(TestCase):
    def test_wikipedia_fetch_selects_table_with_requested_column(self):
        historical = pd.DataFrame({"history": [1]})
        constituents = pd.DataFrame({"Ticker": ["AI.PA"]})
        response = SimpleNamespace(text="<html></html>", raise_for_status=lambda: None)

        with patch.object(stocks_screener.requests, "get", return_value=response), patch.object(
            stocks_screener.pd, "read_html", return_value=[historical, constituents]
        ):
            result = stocks_screener._fetch_wikipedia_table(
                "https://en.wikipedia.org/wiki/CAC_40", required_column="Ticker"
            )

        self.assertIs(result, constituents)

    def test_cac40_tickers_preserve_yahoo_exchange_suffixes(self):
        constituents = pd.DataFrame({"Ticker": ["AI.PA", "MT.AS", None]})

        with patch.object(stocks_screener, "_fetch_wikipedia_table", return_value=constituents):
            tickers = stocks_screener.get_cac40_tickers()

        self.assertEqual(tickers, ["AI.PA", "MT.AS"])