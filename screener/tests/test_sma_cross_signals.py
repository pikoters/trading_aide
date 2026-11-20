import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import numpy as np
import screener.stocks_screener as stocks_screener


def make_fake_df_for_sma_cross():
    n = 22
    idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq='D')
    df = pd.DataFrame(index=idx)
    df['Open'] = 100.0 + np.arange(n)
    df['High'] = df['Open'] + 1.0
    df['Low'] = df['Open'] - 1.0
    df['Close'] = df['Open'] + 0.5
    df['Volume'] = 1000 + np.arange(n) * 10
    df_ind = df.copy()
    # create SMA values where prev SMA100 <= SMA200 and latest SMA100 > SMA200
    df_ind['SMA100'] = 100.0 + 0.01 * np.arange(n)
    df_ind['SMA200'] = 100.0 + 0.01 * np.arange(n)
    df_ind.at[idx[-2], 'SMA100'] = 100.0
    df_ind.at[idx[-2], 'SMA200'] = 100.0
    df_ind.at[idx[-1], 'SMA100'] = 102.0
    df_ind.at[idx[-1], 'SMA200'] = 101.0
    return df, df_ind


def test_sma_cross_up_counts_double(monkeypatch):
    df, df_ind = make_fake_df_for_sma_cross()
    monkeypatch.setattr(stocks_screener.yf, 'download', lambda *args, **kwargs: df)
    monkeypatch.setattr(stocks_screener, 'add_indicators', lambda _df, _inds: df_ind)

    class Args:
        def __init__(self):
            self.start = '2026-01-01'
            self.end = pd.Timestamp.today().strftime('%Y-%m-%d')
            self.rr_ratio = 3.0

    args = Args()
    row = stocks_screener.process_ticker('FAKE', args, indicators=['sma100','sma200'])
    assert row is not None
    assert row.get('sma100_cross_up_sma200') is True
    assert row['score'] >= 2
