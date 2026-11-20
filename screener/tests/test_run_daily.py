import screener.run_daily as run_daily


def test_run_daily_analyzes_all_screener_results_by_default(monkeypatch):
    captured = {}
    monkeypatch.setattr(run_daily.stocks_screener, "main", lambda _args: "test-run")
    monkeypatch.setattr(
        run_daily.stock_analysis,
        "main",
        lambda args: captured.setdefault("args", args),
    )
    monkeypatch.setenv("ANALYSIS_MIN_SCORE", "5")
    monkeypatch.setenv("ANALYSIS_TOP_N", "10")
    monkeypatch.delenv("ANALYSIS_ENABLED", raising=False)

    run_daily.main()

    assert "--min-score" not in captured["args"]
    assert "--top-n" not in captured["args"]
    assert captured["args"][:3] == ["--save-db", "--screener-run-id", "test-run"]


def test_run_daily_can_disable_analysis(monkeypatch):
    analysis_called = False
    monkeypatch.setattr(run_daily.stocks_screener, "main", lambda _args: "test-run")

    def fail_if_called(_args):
        nonlocal analysis_called
        analysis_called = True
        raise AssertionError("analysis should be disabled")

    monkeypatch.setattr(run_daily.stock_analysis, "main", fail_if_called)
    monkeypatch.setenv("ANALYSIS_ENABLED", "false")

    assert run_daily.main() == "test-run"
    assert analysis_called is False


def test_run_daily_rejects_invalid_analysis_toggle(monkeypatch):
    monkeypatch.setattr(run_daily.stocks_screener, "main", lambda _args: "test-run")
    monkeypatch.setenv("ANALYSIS_ENABLED", "sometimes")

    try:
        run_daily.main()
    except ValueError as error:
        assert "ANALYSIS_ENABLED" in str(error)
    else:
        raise AssertionError("invalid ANALYSIS_ENABLED value should fail")
