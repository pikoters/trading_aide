import pandas as pd
import numpy as np
import screener.stocks_screener as stocks_screener


def make_fake_df():
    idx = pd.date_range(end=pd.Timestamp.today(), periods=30, freq='D')
    df = pd.DataFrame(index=idx)
    df['Open'] = 100.0 + np.arange(30)
    df['High'] = df['Open'] + 1.0
    df['Low'] = df['Open'] - 1.0
    df['Close'] = df['Open'] + 0.5
    df['Volume'] = 1000 + np.arange(30) * 10
    return df


def test_process_ticker_outputs_stop_target(monkeypatch):
    # Prepare fake data and ensure add_indicators returns ATR
    df = make_fake_df()
    df_ind = df.copy()
    df_ind['ATRr_14'] = 1.0  # fixed ATR to make target/stop deterministic

    # Patch yfinance.download to avoid network
    monkeypatch.setattr(stocks_screener.yf, 'download', lambda *args, **kwargs: df)
    # Patch add_indicators to return our df with ATR
    monkeypatch.setattr(stocks_screener, 'add_indicators', lambda _df, _inds: df_ind)

    class Args:
        def __init__(self):
            self.start = '2024-01-01'
            self.end = pd.Timestamp.today().strftime('%Y-%m-%d')
            self.rr_ratio = 2.5

    args = Args()
    row = stocks_screener.process_ticker('FAKE', args, indicators=['atr', 'rsi'])

    assert row is not None
    assert 'stop' in row and 'target' in row and 'rr_ratio' in row
    # rr_ratio should be the one we provided
    assert row['rr_ratio'] == 2.5
    # stop/target should be numeric and target > stop
    assert isinstance(row['stop'], float)
    assert isinstance(row['target'], float)
    assert row['target'] > row['stop']
