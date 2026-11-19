"""Command-line entry point for saved and CSV-based stock analysis."""

import argparse
import json

from screener.trade_analysis import (
  analyze_screener_run,
  augment_screener_results,
  build_reference_report,
  fetch_ticker_context,
  format_reference_report,
)


def main(argv=None):
  """Parse analysis CLI options, run the selected workflow, and print reports.

  ``argv`` may be supplied by tests or another command-line entry point; when
  omitted, arguments are read from the process command line.
  """
  parser = argparse.ArgumentParser(description="Analyze screener results and optionally save them to PostgreSQL")
  parser.add_argument("--results", default="green_stocks.csv", help="Screener CSV to analyze")
  parser.add_argument("--tickers", help="Optional comma-separated tickers to analyze")
  parser.add_argument("--min-score", type=float, help="Optional minimum screener score")
  parser.add_argument("--top-n", type=int, help="Optional maximum number of stocks to analyze")
  parser.add_argument("--start", default="2025-01-01", help="History start date (YYYY-MM-DD)")
  parser.add_argument("--rr-ratio", type=float, default=3.0)
  parser.add_argument(
    "--rsi-threshold",
    type=float,
    default=55.0,
    help="TITA RSI entry threshold (50 through 55)",
  )
  parser.add_argument(
    "--macd-zero-tolerance-pct",
    type=float,
    default=0.5,
    help="PAPA MACD zero-line tolerance as a percent of price",
  )
  parser.add_argument(
    "--fishball-support-lookback",
    type=int,
    default=20,
    help="FISHBALL prior-bar support lookback on the 30-minute chart",
  )
  parser.add_argument("--save-db", action="store_true", help="Append this analysis run and snapshots to PostgreSQL")
  parser.add_argument(
    "--screener-run-id",
    nargs="?",
    const="latest",
    help="Analyze captured results for this UUID; omit the value to use the latest screener run",
  )
  args = parser.parse_args(argv)
  if not 50 <= args.rsi_threshold <= 55:
    parser.error("--rsi-threshold must be between 50 and 55")
  if args.macd_zero_tolerance_pct < 0:
    parser.error("--macd-zero-tolerance-pct cannot be negative")
  if args.fishball_support_lookback < 2:
    parser.error("--fishball-support-lookback must be at least 2")

  if args.screener_run_id is not None:
    selected = analyze_screener_run(
      args.screener_run_id,
      tickers=[ticker.strip() for ticker in args.tickers.split(",") if ticker.strip()] if args.tickers else None,
      min_score=args.min_score,
      top_n=args.top_n,
      rr_ratio=args.rr_ratio,
      save_to_db=args.save_db,
      rsi_threshold=args.rsi_threshold,
      macd_zero_tolerance_pct=args.macd_zero_tolerance_pct,
      fishball_support_lookback=args.fishball_support_lookback,
    )
    print(selected[[
      "ticker", "as_of", "close", "score", "entry", "stop", "target", "actionable", "analysis_note",
    ]])
    print_strategy_plans(selected)
    return

  selected = augment_screener_results(
    args.results,
    tickers=[ticker.strip() for ticker in args.tickers.split(",") if ticker.strip()] if args.tickers else None,
    min_score=args.min_score,
    top_n=args.top_n,
    start=args.start,
    rr_ratio=args.rr_ratio,
    save_to_db=args.save_db,
    rsi_threshold=args.rsi_threshold,
    macd_zero_tolerance_pct=args.macd_zero_tolerance_pct,
    fishball_support_lookback=args.fishball_support_lookback,
  )
  print(selected[["ticker", "entry", "stop", "target", "actionable"]])
  print_strategy_plans(selected)

  for ticker in selected["ticker"]:
    context = fetch_ticker_context(ticker, start=args.start, rr_ratio=args.rr_ratio)
    print()
    print(format_reference_report(build_reference_report(context)))


def print_strategy_plans(analysis):
  """Print each ticker's strategy suggestions as sorted JSON."""
  for _, row in analysis.iterrows():
    print()
    print(f"{row['ticker']} strategy suggestions (manual review only):")
    plans = row.get("strategy_plans") or {}
    for name, plan in plans.items():
      print(f"- {name}: {json.dumps(plan, sort_keys=True)}")


if __name__ == "__main__":
  main()