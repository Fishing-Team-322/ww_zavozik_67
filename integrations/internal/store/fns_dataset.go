package store

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fns"
)

const DebtDatasetID = "7707329152-debtam"

type DatasetState struct {
	CompanyID   string          `json:"company_id"`
	DatasetID   string          `json:"dataset_id"`
	Publication fns.Publication `json:"publication"`
	RetrievedAt string          `json:"retrieved_at"`
	Files       int             `json:"files"`
	Documents   int             `json:"documents"`
	Matches     int             `json:"matches"`
}
type DatasetRun struct {
	Status     string `json:"status"`
	Version    string `json:"version,omitempty"`
	ErrorCode  string `json:"error_code,omitempty"`
	FinishedAt string `json:"finished_at"`
}

func (p *Postgres) GetDatasetState(ctx context.Context, company string) (DatasetState, error) {
	s := DatasetState{CompanyID: company, DatasetID: DebtDatasetID}
	var retrieved time.Time
	var published, asOf time.Time
	err := p.DB.QueryRowContext(ctx, `SELECT version,source_url,published_at,dataset_as_of,retrieved_at,files,documents,matches FROM fns_dataset_state WHERE company_id=$1 AND dataset_id=$2`, company, DebtDatasetID).Scan(&s.Publication.Version, &s.Publication.URL, &published, &asOf, &retrieved, &s.Files, &s.Documents, &s.Matches)
	if errors.Is(err, sql.ErrNoRows) {
		return s, nil
	}
	if err != nil {
		return s, err
	}
	s.Publication.PublishedAt = published.Format("2006-01-02")
	s.Publication.DatasetAsOf = asOf.Format("2006-01-02")
	s.RetrievedAt = retrieved.UTC().Format(time.RFC3339)
	return s, nil
}
func (p *Postgres) SaveDatasetState(ctx context.Context, s DatasetState) error {
	_, err := p.DB.ExecContext(ctx, `INSERT INTO fns_dataset_state(company_id,dataset_id,version,source_url,published_at,dataset_as_of,retrieved_at,files,documents,matches) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT(company_id,dataset_id) DO UPDATE SET version=EXCLUDED.version,source_url=EXCLUDED.source_url,published_at=EXCLUDED.published_at,dataset_as_of=EXCLUDED.dataset_as_of,retrieved_at=EXCLUDED.retrieved_at,files=EXCLUDED.files,documents=EXCLUDED.documents,matches=EXCLUDED.matches`, s.CompanyID, DebtDatasetID, s.Publication.Version, s.Publication.URL, s.Publication.PublishedAt, s.Publication.DatasetAsOf, s.RetrievedAt, s.Files, s.Documents, s.Matches)
	return err
}
func (p *Postgres) RecordDatasetRun(ctx context.Context, company, status, version, code string) error {
	_, err := p.DB.ExecContext(ctx, `INSERT INTO fns_dataset_runs(company_id,dataset_id,status,version,error_code) VALUES($1,$2,$3,$4,$5)`, company, DebtDatasetID, status, version, code)
	return err
}
func (p *Postgres) GetDatasetRuns(ctx context.Context, company string) ([]DatasetRun, error) {
	rows, err := p.DB.QueryContext(ctx, `SELECT status,COALESCE(version,''),COALESCE(error_code,''),finished_at FROM fns_dataset_runs WHERE company_id=$1 AND dataset_id=$2 ORDER BY id DESC LIMIT 50`, company, DebtDatasetID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := make([]DatasetRun, 0)
	for rows.Next() {
		var x DatasetRun
		var at time.Time
		if err := rows.Scan(&x.Status, &x.Version, &x.ErrorCode, &at); err != nil {
			return nil, err
		}
		x.FinishedAt = at.UTC().Format(time.RFC3339)
		out = append(out, x)
	}
	return out, rows.Err()
}
func (p *Postgres) TryDatasetLock(ctx context.Context, company string) (func(), bool, error) {
	conn, err := p.DB.Conn(ctx)
	if err != nil {
		return nil, false, err
	}
	var acquired bool
	err = conn.QueryRowContext(ctx, `SELECT pg_try_advisory_lock(hashtext($1))`, "fns_debt:"+company).Scan(&acquired)
	if err != nil {
		conn.Close()
		return nil, false, err
	}
	if !acquired {
		conn.Close()
		return nil, false, nil
	}
	release := func() {
		c, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_, _ = conn.ExecContext(c, `SELECT pg_advisory_unlock(hashtext($1))`, "fns_debt:"+company)
		_ = conn.Close()
	}
	return release, true, nil
}
