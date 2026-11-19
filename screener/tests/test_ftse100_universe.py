from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import pandas as pd

import screener.stocks_screener as stocks_screener


class FTSE100UniverseTests(TestCase):
    def test_wikipedia_fetch_selects_constituents_table(self):
        history = pd.DataFrame({"history": [1]})
        constituents = pd.DataFrame({"Ticker": ["AZN.L"]})
        response = SimpleNamespace(text="<html></html>", raise_for_status=lambda: None)

        with patch.object(stocks_screener.requests, "get", return_value=response), patch.object(
            stocks_screener.pd, "read_html", return_value=[history, constituents]
        ):
            result = stocks_screener._fetch_wikipedia_table(
                "https://en.wikipedia.org/wiki/FTSE_100",
                required_column=("EPIC", "Ticker"),
            )

        self.assertIs(result, constituents)

    def test_ftse100_tickers_preserve_yahoo_exchange_suffixes(self):
        constituents = pd.DataFrame({"Ticker": ["AZN", "BT.A", "HSBA.L", None]})

        with patch.object(stocks_screener, "_fetch_wikipedia_table", return_value=constituents) as fetch_table:
            tickers = stocks_screener.get_ftse100_tickers()

        self.assertEqual(tickers, ["AZN.L", "BT-A.L", "HSBA.L"])
        fetch_table.assert_called_once_with(
            "https://en.wikipedia.org/wiki/FTSE_100",
            required_column=("EPIC", "Ticker"),
        )