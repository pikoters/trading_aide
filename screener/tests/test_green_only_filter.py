import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import screener.stocks_screener as stocks_screener


def make_df(last_green=True):
    n = 22
    idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq='D')
    df = pd.DataFrame(index=idx)
    df['Open'] = 100.0 + np.arange(n)
    df['High'] = df['Open'] + 2.0
    df['Low'] = df['Open'] - 2.0
    if last_green:
        df['Close'] = df['Open'] + 0.5
    else:
        df['Close'] = df['Open'] - 0.5
    df['Volume'] = 1000 + np.arange(n) * 10
    return df


def test_green_only_filters_out_red_last_candle(monkeypatch):
    df_red = make_df(last_green=False)
    monkeypatch.setattr(stocks_screener.yf, 'download', lambda *args, **kwargs: df_red)
    monkeypatch.setattr(stocks_screener, 'add_indicators', lambda df, indicators: df)

    class Args:
        def __init__(self):
            self.start = '2026-01-01'
            self.end = pd.Timestamp.today().strftime('%Y-%m-%d')
            self.rr_ratio = 3.0
            self.green_only = True
            self.above_filters = []
            self.above_mode = 'any'

    row = stocks_screener.process_ticker('FAKE', Args(), indicators=[])
    assert row is None


def test_green_only_keeps_green_last_candle(monkeypatch):
    df_green = make_df(last_green=True)
    monkeypatch.setattr(stocks_screener.yf, 'download', lambda *args, **kwargs: df_green)
    monkeypatch.setattr(stocks_screener, 'add_indicators', lambda df, indicators: df)

    class Args:
        def __init__(self):
            self.start = '2026-01-01'
            self.end = pd.Timestamp.today().strftime('%Y-%m-%d')
            self.rr_ratio = 3.0
            self.green_only = True
            self.above_filters = []
            self.above_mode = 'any'

    row = stocks_screener.process_ticker('FAKE', Args(), indicators=[])
    assert row is not None
