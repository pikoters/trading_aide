package postgresstore

import (
	"encoding/json"
	"os"
	"testing"
)

func TestPythonAnalysisResultRowMapsToGoReadModels(t *testing.T) {
	payload, err := os.ReadFile("../../../../../contracts/analysis_result_row.json")
	if err != nil {
		t.Fatalf("read shared Python persistence fixture: %v", err)
	}
	var row map[string]any
	if err := json.Unmarshal(payload, &row); err != nil {
		t.Fatalf("decode shared persistence fixture: %v", err)
	}

	snapshot := analysisResponseFromJSON(row)
	if snapshot.AnalysisRunID != "56b141db-b46b-43b1-97f1-e24c6386f5cc" ||
		snapshot.ScreenerRunID == nil ||
		*snapshot.ScreenerRunID != "47141ed8-aef5-42a1-a5c9-f6585600ee0d" {
		t.Fatalf("unexpected mapped run identifiers: %#v", snapshot)
	}
	if snapshot.Summary.Ticker != "AAPL" || snapshot.Summary.AsOf != "2026-10-09" ||
		snapshot.Summary.Close != 258 || snapshot.Summary.Score != 6 {
		t.Fatalf("unexpected mapped summary: %#v", snapshot.Summary)
	}
	if snapshot.Summary.Indicators["EMA100"] != 245 ||
		!snapshot.Summary.Signals["rsi_bull"] ||
		snapshot.Plan.Entry == nil || *snapshot.Plan.Entry != 250 ||
		snapshot.StrategyPlans["MAMA_daily"]["status"] != "ENTRY_TRIGGERED" {
		t.Fatalf("unexpected mapped strategy contract: %#v", snapshot)
	}

	result := savedAnalysisFromJSON(snapshot.AnalysisRunID, row)
	if result.AnalysisRunID != snapshot.AnalysisRunID ||
		result.Ticker != snapshot.Summary.Ticker ||
		result.Score != snapshot.Summary.Score ||
		result.Actionable != snapshot.Plan.Actionable {
		t.Fatalf("list-result mapping diverges from ticker analysis: %#v", result)
	}
}
