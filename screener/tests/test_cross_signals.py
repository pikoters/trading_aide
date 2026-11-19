import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import screener.stocks_screener as stocks_screener


def make_fake_df_for_cross():
    # Create 22 rows so process_ticker doesn't bail on short data.
    n = 22
    idx = pd.date_range(end=pd.Timestamp.today(), periods=n, freq='D')
    df = pd.DataFrame(index=idx)
    df['Open'] = 100.0 + np.arange(n)
    df['High'] = df['Open'] + 1.0
    df['Low'] = df['Open'] - 1.0
    df['Close'] = df['Open'] + 0.5
    df['Volume'] = 1000 + np.arange(n) * 10
    df_ind = df.copy()
    # Set EMA values so that the last two rows contain a cross up
    # For rows 0..n-3 keep EMA100<=EMA200; for prev (n-2) set equal, for last (n-1) set EMA100>EMA200
    df_ind['EMA100'] = 100.0 + 0.1 * np.arange(n)
    df_ind['EMA200'] = 100.0 + 0.1 * np.arange(n)
    df_ind.at[idx[-2], 'EMA100'] = 100.0
    df_ind.at[idx[-2], 'EMA200'] = 100.0
    df_ind.at[idx[-1], 'EMA100'] = 102.0
    df_ind.at[idx[-1], 'EMA200'] = 101.0
    df_ind['SMA100'] = df_ind['Close'].rolling(100).mean().fillna(method='ffill')
    df_ind['SMA200'] = df_ind['Close'].rolling(200).mean().fillna(method='ffill')
    return df, df_ind


def test_ema_cross_up_counts_double(monkeypatch):
    df, df_ind = make_fake_df_for_cross()

    # Patch yfinance.download to return the raw df
    monkeypatch.setattr(stocks_screener.yf, 'download', lambda *args, **kwargs: df)
    # Patch add_indicators to return our df_ind
    monkeypatch.setattr(stocks_screener, 'add_indicators', lambda _df, _inds: df_ind)

    class Args:
        def __init__(self):
            self.start = '2026-01-01'
            self.end = pd.Timestamp.today().strftime('%Y-%m-%d')
            self.rr_ratio = 3.0

    args = Args()
    # Request ema indicators so signal generation includes cross
    row = stocks_screener.process_ticker('FAKE', args, indicators=['ema100','ema200'])

    assert row is not None
    # Cross up should be present
    assert row.get('ema100_cross_up_ema200') is True
    # The weighted score should reflect +2 for the cross (at least 2)
    assert row['score'] >= 2
