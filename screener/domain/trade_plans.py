"""Pure domain calculations for trade plans and report formatting."""

from decimal import Decimal, ROUND_HALF_UP
import math


def value_or_none(row, column):
    """Return a finite numeric value or ``None`` for missing/non-finite data.

    Values must be convertible to ``float``; conversion errors are propagated.
    """
    value = row.get(column, float("nan"))
    if value is None:
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def round_price(value, decimals):
    """Round a price with decimal half-up semantics; preserve ``None`` inputs."""
    if value is None:
        return None
    quantum = Decimal("1").scaleb(-decimals)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def build_long_trade_plan(latest, rr_ratio=3.0, price_decimals=2):
    """Build a long pullback plan using MA support and ATR risk.

    Entry is the highest available EMA100/EMA200 support below the latest close.
    If neither support is below price, the plan is not actionable. Stop is one
    ATR below entry and target is ``rr_ratio`` times the entry-to-stop risk.
    """
    close = value_or_none(latest, "Close")
    atr = value_or_none(latest, "ATRr_14")
    supports = [
        (name, value_or_none(latest, name))
        for name in ("EMA100", "EMA200")
        if value_or_none(latest, name) is not None
    ]
    supports_below_price = [
        (name, value)
        for name, value in supports
        if close is not None and value < close
    ]
    if close is None or atr is None or atr <= 0 or not supports_below_price:
        return {
            "setup": "long_pullback",
            "actionable": False,
            "entry_rule": "limit at highest available EMA100/EMA200 below close",
            "entry": None,
            "entry_support": None,
            "stop": None,
            "target": None,
            "risk_per_share": None,
            "rr_ratio": float(rr_ratio),
        }

    entry_support, support = max(supports_below_price, key=lambda item: item[1])
    entry = support
    stop = entry - atr
    risk = entry - stop
    target = entry + float(rr_ratio) * risk
    rounded_entry = round_price(entry, price_decimals)
    rounded_stop = round_price(stop, price_decimals)
    rounded_target = round_price(target, price_decimals)
    rounded_risk = round_price(risk, price_decimals)
    actionable = bool(
        rounded_entry > rounded_stop
        and rounded_target > rounded_entry
        and rounded_risk > 0
    )
    return {
        "setup": "long_pullback",
        "actionable": actionable,
        "entry_rule": "limit at highest available EMA100/EMA200 below close",
        "entry": rounded_entry,
        "entry_support": entry_support,
        "stop": rounded_stop,
        "target": rounded_target,
        "risk_per_share": rounded_risk,
        "rr_ratio": float(rr_ratio),
    }


def build_reference_report(
    context,
    atr_proxy_pct=0.01,
    pullback_buffer_pct=0.0025,
    conservative_atr_multiple=2.0,
    conservative_rr=1.5,
    swing_window=20,
    price_decimals=2,
):
    """Build a report containing reference metrics and two advisory long plans.

    ``context`` is the mapping returned by market-context retrieval and must
    contain ``history``, ``indicators``, ``signals``, ``ticker``, ``as_of``,
    ``close``, and optionally ``volume``. The conservative plan uses an EMA50
    pullback and percentage-based ATR proxy; the breakout plan uses the prior
    ``swing_window`` high and checks volume confirmation.
    """
    history = context["history"]
    indicators = context["indicators"]
    close = context["close"]
    ema50 = indicators.get("EMA50")
    atr_proxy = round(close * atr_proxy_pct, 3) if close is not None else None
    pullback_entry = (
        round(ema50 * (1 + pullback_buffer_pct), price_decimals)
        if ema50 is not None else None
    )
    conservative_risk = (
        round(conservative_atr_multiple * atr_proxy, 3)
        if atr_proxy is not None else None
    )
    conservative_stop = (
        pullback_entry - conservative_risk
        if pullback_entry is not None and conservative_risk is not None else None
    )
    conservative_target = None
    if pullback_entry is not None and conservative_risk is not None:
        conservative_target = float(
            Decimal(str(pullback_entry))
            + Decimal(str(conservative_rr)) * Decimal(str(conservative_risk))
        )

    prior_history = history.iloc[:-1] if len(history) > 1 else history
    swing_high = (
        None if prior_history.empty else
        round(float(prior_history.tail(swing_window)["High"].max()), price_decimals)
    )
    latest_volume = context.get("volume")
    volume_avg20 = indicators.get("VolumeAvg20")
    breakout_stop = (
        swing_high - atr_proxy
        if swing_high is not None and atr_proxy is not None else None
    )
    breakout_target = (
        swing_high + 3 * atr_proxy
        if swing_high is not None and atr_proxy is not None else None
    )
    bull_flags = {
        name: value for name, value in context["signals"].items()
        if name.endswith("_bull")
    }
    distance_from_ema50 = (
        close / ema50 - 1 if close is not None and ema50 else None
    )

    def rounded(value):
        """Round an optional price using the report's configured precision."""
        return round_price(value, price_decimals)

    return {
        "ticker": context["ticker"],
        "as_of": context["as_of"],
        "reference": {
            "close": rounded(close),
            "ema50": rounded(ema50),
            "ema100": rounded(indicators.get("EMA100")),
            "ema200": rounded(indicators.get("EMA200")),
            "rsi_14": rounded(indicators.get("RSI_14")),
            "all_bull_flags": bool(bull_flags) and all(bull_flags.values()),
            "bull_flags": bull_flags,
            "distance_from_ema50": distance_from_ema50,
        },
        "conservative_pullback": {
            "entry": rounded(pullback_entry),
            "stop": rounded(conservative_stop),
            "target": rounded(conservative_target),
            "risk": rounded(conservative_risk),
            "atr_proxy": round(atr_proxy, 3) if atr_proxy is not None else None,
            "rule": "limit at EMA50 + 0.25%; stop at entry - 2x ATR proxy; target at 1.5R",
        },
        "aggressive_breakout": {
            "entry": rounded(swing_high),
            "stop": rounded(breakout_stop),
            "target": rounded(breakout_target),
            "swing_high": rounded(swing_high),
            "volume": latest_volume,
            "volume_avg20": volume_avg20,
            "volume_confirmed": bool(
                latest_volume is not None
                and volume_avg20 is not None
                and latest_volume > volume_avg20
            ),
            "rule": "buy above recent swing high only when Volume > VolumeAvg20; stop at 1x ATR proxy; target at 3R",
        },
    }


def _format_price(value):
    return f"{value:.2f}" if value is not None else "n/a"


def format_reference_report(report):
    """Render the mapping returned by :func:`build_reference_report` as text."""
    reference = report["reference"]
    conservative = report["conservative_pullback"]
    breakout = report["aggressive_breakout"]
    distance = reference["distance_from_ema50"]
    distance_text = f"{distance:.1%}" if distance is not None else "n/a"
    return "\n".join([
        f"{report['ticker']} — reference data ({report['as_of']})",
        f"- Close: {_format_price(reference['close'])}",
        f"- EMA50: {_format_price(reference['ema50'])}",
        f"- EMA100: {_format_price(reference['ema100'])}",
        f"- EMA200: {_format_price(reference['ema200'])}",
        f"- RSI_14: {_format_price(reference['rsi_14'])}",
        f"- All bull flags: {reference['all_bull_flags']}",
        f"- Distance from EMA50: {distance_text}",
        "- Plan: breakout-friendly when volume confirms; conservative pullback is also valid.",
        f"- ATR proxy: 1% of price = {_format_price(conservative['atr_proxy'])}",
        f"- Conservative entry: EMA50 + 0.25% = {_format_price(conservative['entry'])}",
        f"- Conservative stop: entry - 2x ATR = {_format_price(conservative['stop'])}",
        f"- Conservative target (1.5R): {_format_price(conservative['target'])}",
        f"- Aggressive breakout entry: above swing high {_format_price(breakout['entry'])}",
        f"- Breakout volume: {breakout['volume_confirmed']} ({breakout['volume']} > {breakout['volume_avg20']})",
        f"- Breakout stop: {_format_price(breakout['stop'])}; target (3R): {_format_price(breakout['target'])}",
        f"- Order rule: limit buy at {_format_price(conservative['entry'])}; stop {_format_price(conservative['stop'])}; target {_format_price(conservative['target'])}; or buy breakout above {_format_price(breakout['entry'])} with volume confirmation.",
    ])
