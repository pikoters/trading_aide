"""Application contracts for analysis providers and persistence."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

import pandas as pd


class AnalysisRepository(Protocol):
    """Persistence capabilities required by the analysis use cases.

    Implementations own serialization and transaction behavior; workflows use
    these methods without depending on a particular database or ORM.
    """

    def load_screener_run(
        self, run_id: str
    ) -> tuple[dict[str, Any], pd.DataFrame]:
        """Load a run's metadata and ticker rows; ``latest`` selects newest."""
        ...

    def start_analysis_run(self, run_metadata: dict[str, Any]) -> None:
        """Persist analysis-run metadata before saving any ticker results."""
        ...

    def save_analysis_result(
        self, analysis_run_id: str, result: dict[str, Any]
    ) -> None:
        """Persist one ticker result associated with an analysis run."""
        ...

    def finish_analysis_run(
        self,
        analysis_run_id: str,
        finished_at: datetime,
        status: str = "completed",
    ) -> None:
        """Complete or fail an analysis run with its finish timestamp."""
        ...

    def close(self) -> None:
        """Release adapter-owned database resources."""
        ...


@dataclass(frozen=True)
class AnalysisDependencies:
    """Runtime adapters supplied when composing an analysis workflow.

    ``repository_factory`` creates a repository per invocation;
    ``fetch_ticker_context`` retrieves enriched market context; and
    ``fetch_strategy_plans`` evaluates the configured strategies for history.
    """

    repository_factory: Callable[[], AnalysisRepository]
    fetch_ticker_context: Callable[..., dict[str, Any]]
    fetch_strategy_plans: Callable[..., dict[str, Any]]
