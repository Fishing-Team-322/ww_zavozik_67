package product

import (
	"context"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

// Compare the last two data revisions, rather than two duplicate page reads.
// This is a comparison of saved forecasts, not attribution to one missed payment.
func (s *Service) forecastChange(ctx context.Context, cid string) (Doc, error) {
	out := Doc{"gap_date": nil, "gap_date_before": nil, "probability_before": nil, "probability_after": nil, "revision_before": nil, "revision_after": nil}
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
		forecast := store.Decode(raw)
		probability := 0.0
		var date any
		for _, gap := range docs(forecast["gaps"]) {
			if date == nil {
				date = gap["date"]
			}
			if number(gap, "probability") > probability {
				probability = number(gap, "probability")
			}
		}
		if index == 0 {
			out["revision_after"], out["probability_after"], out["gap_date"] = revision, probability, date
		} else {
			out["revision_before"], out["probability_before"], out["gap_date_before"] = revision, probability, date
		}
		index++
	}
	return out, rows.Err()
}
