package product

import (
	"context"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

// One cheap tenant-scoped probe lets open screens observe completed background jobs.
// Forecast reads do not change this fingerprint: they can safely invalidate the UI.
func (s *Service) updates(ctx context.Context, uid, cid string) (Result, error) {
	if _, e := s.DB.GetCompany(ctx, uid, cid); e != nil {
		return Result{}, e
	}
	var raw []byte
	e := s.DB.Pool.QueryRow(ctx, `SELECT jsonb_build_object(
'data_revision',c.data_revision,'forecast_revision',(SELECT max(revision) FROM forecast_runs WHERE company_id=c.id),
'data_as_of',(SELECT max(op_date)::timestamptz FROM operations WHERE company_id=c.id),'pending_jobs',(SELECT count(*) FROM product_jobs WHERE company_id=c.id AND status IN ('queued','running')),
'last_job_finished_at',(SELECT max(finished_at) FROM product_jobs WHERE company_id=c.id),
'last_job_error',(SELECT error FROM product_jobs WHERE company_id=c.id AND finished_at IS NOT NULL ORDER BY finished_at DESC,id DESC LIMIT 1))
FROM companies c WHERE c.id=$1`, cid).Scan(&raw)
	if e != nil {
		return Result{}, e
	}
	return ok(store.Decode(raw))
}
