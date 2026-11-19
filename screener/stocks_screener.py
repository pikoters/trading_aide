#!/usr/bin/env python3
"""Daily stock screener for US + Europe using Yahoo Finance + pandas_ta indicators."""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from io import StringIO
from uuid import uuid4

import pandas as pd
import screener.infrastructure.postgres.repository as persistence
import yfinance as yf
import requests

import logging as log
from sqlalchemy.exc import SQLAlchemyError

from screener.domain.indicators import (
    IndicatorCalculationError,
    add_indicators,
    compute_projected_1_3_target,
    compute_projected_target,
    evaluate_signals,
    ta,
)

log.basicConfig(level=log.INFO)


def _fetch_wikipedia_table(url, required_column=None):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Could not fetch %s: %s", url, exc)
        return None

    try:
        tables = pd.read_html(StringIO(response.text), header=0)
    except ValueError as exc:
        log.warning("Could not parse %s: %s", url, exc)
        return None

    if not tables:
        return None
    if required_column is not None:
        required_columns = (required_column,) if isinstance(required_column, str) else required_column
        for table in tables:
            if any(column in table.columns for column in required_columns):
                return table
        log.warning("Could not find a table with any of columns %r on %s", required_columns, url)
        return None
    return tables[0]


def get_sp500_tickers():
    """Fetch and normalize the S&P 500 symbols from Wikipedia.

    Returns an empty list when the remote table is unavailable or malformed.
    """
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    df = _fetch_wikipedia_table(url)
    if df is None or "Symbol" not in df.columns:
        return []
    return sorted(df["Symbol"].dropna().str.replace("\\.", "-", regex=True).tolist())


def get_nasdaq_tickers():
    """Fetch active Nasdaq-listed non-ETF symbols from Nasdaq Trader.

    Test issues and ETFs are excluded. Network, parse, or schema failures are
    logged and return an empty list.
    """
    url = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 stock-screener/1.0"},
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Could not fetch Nasdaq symbols from %s: %s", url, exc)
        return []

    try:
        symbols = pd.read_csv(StringIO(response.text), sep="|", dtype=str)
    except (pd.errors.ParserError, ValueError) as exc:
        log.warning("Could not parse Nasdaq symbols from %s: %s", url, exc)
        return []

    required_columns = {"Symbol", "Test Issue", "ETF"}
    if not required_columns.issubset(symbols.columns):
        log.warning("Nasdaq symbol file is missing required columns: %s", required_columns)
        return []

    active_stocks = symbols[
        symbols["Test Issue"].str.upper().eq("N")
        & symbols["ETF"].str.upper().eq("N")
    ]
    tickers = active_stocks["Symbol"].dropna().str.strip().str.upper()
    return sorted(tickers[tickers.str.fullmatch(r"[A-Z0-9.^=-]{1,20}")].tolist())


def get_dax_tickers():
    """Fetch and normalize DAX ticker symbols from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/DAX"
    df = _fetch_wikipedia_table(url)
    if df is None:
        return []
    if "Ticker symbol" in df.columns:
        return sorted(df["Ticker symbol"].dropna().str.replace("\\.", "-", regex=True).tolist())
    return []


def get_ftse100_tickers():
    """Fetch FTSE 100 EPIC symbols and normalize them for Yahoo Finance."""
    url = "https://en.wikipedia.org/wiki/FTSE_100"
    df = _fetch_wikipedia_table(url, required_column=("EPIC", "Ticker"))
    if df is None:
        return []
    col = "EPIC" if "EPIC" in df.columns else ("Ticker" if "Ticker" in df.columns else None)
    if col:
        symbols = df[col].dropna().astype(str).str.strip().tolist()
        yahoo_symbols = [
            symbol if symbol.endswith(".L") else f"{symbol.replace('.', '-')}.L"
            for symbol in symbols
        ]
        return sorted(yahoo_symbols)
    return []


def get_cac40_tickers():
    """Fetch CAC 40 ticker symbols from Wikipedia."""
    url = "https://en.wikipedia.org/wiki/CAC_40"
    df = _fetch_wikipedia_table(url, required_column="Ticker")
    if df is None:
        return []
    if "Ticker" in df.columns:
        return sorted(df["Ticker"].dropna().astype(str).str.strip().tolist())
    return []


def universe_tickers(args):
    """Combine requested symbols, named universes, and an optional symbol file.

    Symbols are uppercased, de-duplicated, and sorted. ``args`` is the parsed
    CLI namespace; an empty selection raises ``ValueError`` and ``max_symbols``
    truncates the sorted list when set.
    """
    tickers = set()
    if args.symbols:
        tickers.update(x.strip().upper() for x in args.symbols.split(",") if x.strip())

    if args.universe:
        for u in args.universe.split(","):
            u = u.strip().lower()
            if u == "sp500":
                tickers.update(get_sp500_tickers())
            elif u == "nasdaq":
                tickers.update(get_nasdaq_tickers())
            elif u == "dow":
                tickers.update(["AAPL", "MSFT", "INTC", "IBM", "JNJ", "V", "WMT", "JPM", "PG", "KO", "DIS", "MCD", "CSCO", "HD", "MRK", "NKE", "UNH", "VZ", "TRV", "RTX", "CAT", "BA", "AXP", "XOM", "CVX", "GS", "WBA", "HD", "MMM", "UTX"])
            elif u == "dax":
                tickers.update(get_dax_tickers())
            elif u == "ftse100":
                tickers.update(get_ftse100_tickers())
            elif u == "cac40":
                tickers.update(get_cac40_tickers())
            elif u == "all-eu":
                tickers.update(get_dax_tickers())
                tickers.update(get_ftse100_tickers())
                tickers.update(get_cac40_tickers())
            else:
                print(f"Warning: unknown universe '{u}' -> ignored", file=sys.stderr)

    if args.symbols_file:
        p = Path(args.symbols_file)
        if p.exists():
            raw = p.read_text().splitlines()
            tickers.update([x.strip().upper() for x in raw if x.strip()])

    if not tickers:
        raise ValueError("No tickers selected. Use --symbols or --universe or --symbols-file")

    if args.max_symbols:
        return sorted(tickers)[: args.max_symbols]

    return sorted(tickers)


def process_ticker(ticker, args, indicators, rr_ratio=None):
    """Fetch and score one ticker, returning its persisted/output row.

    Returns ``None`` for unavailable or insufficient market history and
    raises ``IndicatorCalculationError`` when a selected indicator fails.
    """
    try:
        df = yf.download(ticker, start=args.start, end=args.end, progress=False, interval="1d")
    except Exception as e:
        print(f"{ticker} error downloading: {e}", file=sys.stderr)
        return None
    if df.empty or len(df) < 21:
        return None

    # Handle MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Ensure we have the required columns
    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    if not all(col in df.columns for col in required_cols):
        print(f"{ticker} missing required columns", file=sys.stderr)
        return None

    # Ensure indicators include any moving averages required by the `--above` filter
    required_inds = set(indicators)
    if getattr(args, "save_db", False):
        required_inds.update(("ema100", "ema200", "atr"))
    above_filters = getattr(args, "above_filters", []) or []
    for f in above_filters:
        if f in ("ema50", "ema100", "ema200", "sma50", "sma100", "sma200"):
            required_inds.add(f)
    df_ind = add_indicators(df, list(required_inds))
    last = df_ind.iloc[-1]
    prev = df_ind.iloc[-2] if len(df_ind) >= 2 else None
    if getattr(args, "green_only", False):
        close_val = float(last.get("Close", float("nan")))
        open_val = float(last.get("Open", float("nan")))
        if pd.isna(close_val) or pd.isna(open_val):
            log.info(f"Skipping {ticker}: missing OHLC values for green-only filter")
            return None
        if close_val <= open_val:
            log.info(f"Skipping {ticker}: last candle is not green (close={close_val}, open={open_val})")
            return None
    # If user requested filtering by being above certain MAs/EMAs, enforce it here.
    if above_filters:
        col_map = {
            "ema100": "EMA100",
            "ema200": "EMA200",
            "sma100": "SMA100",
            "sma200": "SMA200",
        }
        close_val = last.get("Close", float("nan"))
        if pd.isna(close_val):
            log.info(f"Skipping {ticker}: missing Close value")
            return None
        results = []
        for f in above_filters:
            col = col_map.get(f)
            if not col:
                results.append(False)
                continue
            val = last.get(col, float("nan"))
            results.append(not pd.isna(val) and close_val > val)
        mode = getattr(args, "above_mode", "any")
        if mode == "all":
            ok = all(results)
        else:
            ok = any(results)
        if not ok:
            log.info(f"Skipping {ticker}: Close not above requested MAs {above_filters} (mode={mode})")
            return None
    signals = evaluate_signals(last, indicators, prev=prev)
    # Determine reward-to-risk ratio preference: explicit rr_ratio arg, then args.rr_ratio, else 3.0
    rr_pref = rr_ratio if rr_ratio is not None else getattr(args, "rr_ratio", 3.0)
    rr = compute_projected_target(last, rr_ratio=rr_pref)

    row = {
        "ticker": ticker,
        "date": last.name.date() if hasattr(last.name, "date") else last.name,
        "close": last["Close"],
    }
    row.update({k: last.get(k, float("nan")) for k in ["ALMA", "MACDh_12_26_9", "AO", "PSARl_0.02_0.2", "EMA50", "EMA100", "EMA200", "SMA100", "SMA200", "BBM_20_2.0", "STOCHRSIk_14_14_3_3", "TEMA_21", "VolumeAvg20", "RSI_14", "ATRr_14", "CCI_20", "WILLR_14", "ADX_14", "OBV", "MOM_10", "ROC_12", "KCLe_20_2", "ISA_9", "ADOSC", "VPT"]})
    # include SMA50 if present
    row.update({"SMA50": last.get("SMA50", float("nan"))})
    row.update(signals)
    # Use generic column names to reflect arbitrary rr ratios
    row["stop"] = rr["stop"]
    row["target"] = rr["target"]
    row["rr_ratio"] = rr["ratio"]
    # Score signals with weighting: regular true signals = +1,
    # cross_up signals = +2, cross_down signals = -2 (penalty).
    score = 0
    for name, val in signals.items():
        if not val:
            continue
        lname = name.lower()
        if "cross_up" in lname:
            score += 2
        elif "cross_down" in lname:
            score -= 2
        else:
            score += 1
    row["score"] = score
    # Convert date to string for logging
    row["date"] = str(row["date"])
    log.info(f"Processed {ticker}: score={row['score']}, close={row['close']:.2f}")
    return row


def main(argv=None):
    """Run the batch screener and optionally write CSV/PostgreSQL results.

    ``argv`` may be supplied for programmatic invocation.     Returns the generated screener run UUID. The run and rows are written to
    PostgreSQL only when ``--save-db`` is enabled.
    """
    parser = argparse.ArgumentParser(description="US + Europe stock screener with selectable indicators")
    parser.add_argument("--symbols", help="Comma-separated tickers")
    parser.add_argument("--symbols-file", help="File path with one ticker per line")
    parser.add_argument(
        "--universe",
        default="",
        help="Comma-separated universes: sp500,nasdaq,dow,dax,ftse100,cac40,all-eu "
        "(nasdaq uses Nasdaq-listed non-ETF stocks)",
    )
    parser.add_argument("--indicators", default="alma,macd,awesome,psar,moving_average_triple,bollinger,stochrsi,triple_ema,volume,rsi,atr,cci,williams,adx,obv,momentum,roc,keltner,ichimoku,adosc,vpt", help="Comma-separated indicator names")
    parser.add_argument("--start", default="2020-01-01", help="Start date YYYY-MM-DD")
    parser.add_argument("--end", default=pd.Timestamp.today().strftime("%Y-%m-%d"), help="End date YYYY-MM-DD")
    parser.add_argument("--max-symbols", type=int, default=200, help="Max number of symbols to screen (performance)")
    parser.add_argument("--output", help="Optional output CSV file; omitted by default")
    parser.add_argument("--save-db", action="store_true", help="Append this screener run and its results to PostgreSQL")
    parser.add_argument("--rr-ratio", type=float, default=3.0, help="Reward-to-risk ratio (e.g., 3.0 for 1:3)")
    parser.add_argument("--above", default="", help="Comma-separated filters to require Close above given MA/EMA. Choices: ema200,ema100,sma200,sma100")
    parser.add_argument("--above-mode", choices=("any", "all"), default="any", help="Whether Close must be above any or all of the listed MAs (any|all)")
    parser.add_argument("--green-only", action="store_true", help="Only screen tickers whose last candle closed above its open")
    args = parser.parse_args(argv)

    indicators = [i.strip().lower() for i in args.indicators.split(",") if i.strip()]
    tickers = universe_tickers(args)

    # normalize above filters into args for downstream use
    args.above_filters = [x.strip().lower() for x in args.above.split(",") if x.strip()]
    run_id = str(uuid4())
    started_at = datetime.now(timezone.utc)

    print(f"Screening {len(tickers)} tickers from {args.universe} using {indicators} (above filters: {args.above_filters})")

    rows = []
    failed_tickers = []
    for i, ticker in enumerate(tickers, start=1):
        print(f"{i}/{len(tickers)}: {ticker}", end="\r")
        try:
            row = process_ticker(ticker, args, indicators)
        except IndicatorCalculationError:
            failed_tickers.append(ticker)
            log.exception("Skipping %s because indicator calculation failed", ticker)
            continue
        if row:
            rows.append(row)
            log.info(f"{ticker} processed successfully with score {row['score']}")
            # log.info(row)
        time.sleep(0.12)

    if failed_tickers:
        log.warning(
            "Indicator calculations failed for %d ticker(s): %s",
            len(failed_tickers),
            ", ".join(failed_tickers),
        )

    df_out = pd.DataFrame(rows)
    if rows:
        df_out = df_out.sort_values(["score", "close"], ascending=[False, False])
        if args.save_db:
            df_out.insert(0, "run_id", run_id)
        if args.output:
            df_out.to_csv(args.output, index=False)
            print(f"\nDone. Saved {len(df_out)} rows to {args.output}")
        else:
            print(f"\nDone. Processed {len(df_out)} rows without CSV output")
    else:
        print("No results, check the ticker list or data availability.")

    if args.save_db:
        run_metadata = {
            "run_id": run_id,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc),
            "universe": args.universe,
            "selected_symbols": ",".join(tickers),
            "indicators": ",".join(indicators),
            "start_date": args.start,
            "end_date": args.end,
            "max_symbols": args.max_symbols,
            "green_only": args.green_only,
            "above_filters": ",".join(args.above_filters),
            "above_mode": args.above_mode,
            "rr_ratio": args.rr_ratio,
            "result_count": len(df_out),
            "output_file": args.output or "",
        }
        datasource = persistence.PersistenceManager()
        try:
            datasource.save_screener_run(run_metadata, df_out)
            print(f"Saved run {run_id} and {len(df_out)} results to PostgreSQL")
        except SQLAlchemyError as exc:
            log.exception("Could not save screener run to PostgreSQL")
            raise SystemExit(1) from exc
        finally:
            datasource.close()

    if not rows:
        return run_id

    return run_id

if __name__ == "__main__":
    main()
