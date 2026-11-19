"""Scheduled entry point composing screener and analysis CLI workflows."""

import os

import screener.stock_analysis as stock_analysis
import screener.stocks_screener as stocks_screener


def main():
    """Run the scheduled screener, then analyze its saved run when enabled.

    Runtime options are read from the ``SCREENER_*``, ``ANALYSIS_*``, and
    ``RR_RATIO`` environment variables. Raises on a missing run identifier or
    invalid analysis-enabled configuration.
    """
    screener_args = [
        "--universe", os.getenv("SCREENER_UNIVERSE", "all-eu,sp500"),
        "--max-symbols", os.getenv("SCREENER_MAX_SYMBOLS", "1000"),
        "--start", os.getenv("SCREENER_START_DATE", "2020-01-01"),
        "--rr-ratio", os.getenv("RR_RATIO", "3.0"),
        "--save-db",
    ]
    output_path = os.getenv("SCREENER_OUTPUT")
    if output_path:
        screener_args.extend(["--output", output_path])
    if os.getenv("SCREENER_GREEN_ONLY", "false").lower() == "true":
        screener_args.append("--green-only")

    screener_run_id = stocks_screener.main(screener_args)
    if not screener_run_id:
        raise RuntimeError("Screener did not return a run ID")

    analysis_enabled = os.getenv("ANALYSIS_ENABLED", "true").strip().lower()
    if analysis_enabled not in {"true", "1", "yes", "on", "false", "0", "no", "off"}:
        raise ValueError(
            "ANALYSIS_ENABLED must be one of true/false, 1/0, yes/no, or on/off"
        )
    if analysis_enabled in {"false", "0", "no", "off"}:
        return screener_run_id

    analysis_args = [
        "--save-db",
        "--screener-run-id", screener_run_id,
        "--rr-ratio", os.getenv("RR_RATIO", "3.0"),
        "--rsi-threshold", os.getenv("ANALYSIS_RSI_THRESHOLD", "55"),
        "--macd-zero-tolerance-pct", os.getenv("ANALYSIS_MACD_ZERO_TOLERANCE_PCT", "0.5"),
        "--fishball-support-lookback", os.getenv("ANALYSIS_FISHBALL_SUPPORT_LOOKBACK", "20"),
    ]
    stock_analysis.main(analysis_args)


if __name__ == "__main__":
    main()