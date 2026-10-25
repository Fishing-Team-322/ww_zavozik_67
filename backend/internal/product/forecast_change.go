package product

import (
	"context"
	"math"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

// Compare the last two data revisions, rather than two duplicate page reads.
// This is a comparison of saved forecasts, not attribution to one missed payment.
func (s *Service) forecastChange(ctx context.Context, cid string) (Doc, error) {
	out := Doc{"gap_date": nil, "gap_date_before": nil, "probability_before": nil, "probability_after": nil, "probability_reliable_before": false, "probability_reliable_after": false, "revision_before": nil, "revision_after": nil}
	rows, e := s.DB.Pool.Query(ctx, `SELECT revision,payload FROM (SELECT DISTINCT ON(revision) revision,payload,created_at FROM forecast_runs WHERE company_id=$1 AND horizon=30 ORDER BY revision DESC,created_at DESC) f ORDER BY revision DESC LIMIT 2`, cid)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	index := 0
	for rows.Next() {
		var revision int64
		var raw []byte
		if e = rows.Scan(&revision, &raw); e != nil {
			return nil, e
		}
		probability, date, reliable := savedForecastRisk(store.Decode(raw), s.currentDay())
		if index == 0 {
			out["revision_after"], out["probability_after"], out["gap_date"] = revision, probability, date
			out["probability_reliable_after"] = reliable
		} else {
			out["revision_before"], out["probability_before"], out["gap_date_before"] = revision, probability, date
			out["probability_reliable_before"] = reliable
		}
		index++
	}
	return out, rows.Err()
}

// Saved flags age with the statement. Recheck the snapshot's own provenance
// and dates instead of borrowing reliability from the current company's model.
func savedForecastRisk(snapshot Doc, now time.Time) (probability, date any, reliable bool) {
	if _, err := day(text(snapshot, "as_of")); err != nil {
		return nil, nil, false
	}
	previouslyReliable := reliableProbability(snapshot)
	checked := Doc{}
	for key, value := range snapshot {
		checked[key] = value
	}
	checked["gaps"] = []Doc{}
	annotateForecast(checked, now, int(number(snapshot, "unconfirmed_recurring")))
	reliable = previouslyReliable && reliableProbability(checked)
	for _, gap := range docs(snapshot["gaps"]) {
		if date == nil {
			date = gap["date"]
		}
		p, valid := gap["probability"].(float64)
		if !valid || math.IsNaN(p) || math.IsInf(p, 0) || p < 0 || p > 1 || gap["probability_reliable"] == false {
			reliable = false
			continue
		}
		if probability == nil || p > probability.(float64) {
			probability = p
		}
	}
	if !reliable {
		probability = nil
	}
	// An empty alert list only means the warning threshold was not reached;
	// it cannot establish zero probability across all simulated paths.
	return probability, date, reliable && probability != nil
}
