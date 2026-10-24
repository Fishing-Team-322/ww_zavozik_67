package store

import (
	"context"
	"database/sql"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"strconv"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	_ "github.com/jackc/pgx/v5/stdlib"
)

//go:embed migrations/001_init.sql
var migration1 string

//go:embed migrations/002_actual_versions.sql
var migration2 string

type Postgres struct{ DB *sql.DB }

func OpenPostgres(ctx context.Context, dsn string) (*Postgres, error) {
	if dsn == "" {
		return nil, errors.New("database URL required")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, errors.New("cannot open database")
	}
	db.SetMaxOpenConns(8)
	db.SetConnMaxLifetime(30 * time.Minute)
	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return nil, errors.New("database unavailable")
	}
	if _, err := db.ExecContext(ctx, migration1); err != nil {
		db.Close()
		return nil, errors.New("database migration failed")
	}
	if _, err := db.ExecContext(ctx, migration2); err != nil {
		db.Close()
		return nil, errors.New("database migration failed")
	}
	return &Postgres{DB: db}, nil
}

func (p *Postgres) Close() error                    { return p.DB.Close() }
func (p *Postgres) Ready(ctx context.Context) error { return p.DB.PingContext(ctx) }

func (p *Postgres) Save(batch contracts.ImportBatch) (contracts.ImportBatch, error) {
	if batch.CompanyID == "" {
		return batch, errors.New("company_id required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	tx, err := p.DB.BeginTx(ctx, &sql.TxOptions{})
	if err != nil {
		return batch, errors.New("database transaction failed")
	}
	defer tx.Rollback()
	// Serialize imports for a company; hash collisions only reduce concurrency.
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, batch.CompanyID); err != nil {
		return batch, errors.New("database lock failed")
	}
	freshOps := make([]contracts.Operation, 0, len(batch.Operations))
	for _, op := range batch.Operations {
		id := op.ExternalID
		if id == "" {
			id = op.DedupKey
		}
		var previous []byte
		err := tx.QueryRowContext(ctx, `SELECT payload FROM actual_operations WHERE company_id=$1 AND dedup_key=$2 FOR UPDATE`, batch.CompanyID, op.DedupKey).Scan(&previous)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return batch, errors.New("read actual operation failed")
		}
		if err == nil {
			var old contracts.Operation
			if json.Unmarshal(previous, &old) != nil {
				return batch, errors.New("invalid stored operation")
			}
			before, after := old, op
			before.Version, after.Version = 0, 0
			if reflect.DeepEqual(before, after) {
				batch.Stats.Duplicates++
				batch.Stats.Accepted--
				continue
			}
			op.Version = old.Version + 1
		} else {
			op.Version = 1
		}
		payload, e := json.Marshal(op)
		if e != nil {
			return batch, e
		}
		_, e = tx.ExecContext(ctx, `INSERT INTO actual_operations(company_id,source_kind,external_id,dedup_key,version,payload) VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT(company_id,dedup_key) DO UPDATE SET version=EXCLUDED.version,payload=EXCLUDED.payload`, batch.CompanyID, op.SourceKind, id, op.DedupKey, op.Version, payload)
		if e != nil {
			return batch, errors.New("save actual operation failed")
		}
		freshOps = append(freshOps, op)
	}
	batch.Operations = freshOps
	freshPlans := make([]contracts.PlannedEvent, 0, len(batch.PlannedEvents))
	for _, plan := range batch.PlannedEvents {
		var oldPayload []byte
		err := tx.QueryRowContext(ctx, `SELECT payload FROM planned_events WHERE company_id=$1 AND source_kind=$2 AND external_id=$3 FOR UPDATE`, batch.CompanyID, plan.SourceKind, plan.ExternalID).Scan(&oldPayload)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return batch, errors.New("read plan failed")
		}
		if err == nil {
			var old contracts.PlannedEvent
			if json.Unmarshal(oldPayload, &old) != nil {
				return batch, errors.New("invalid stored plan")
			}
			before, after := old, plan
			before.Version, after.Version = 0, 0
			before.ObservedAt, after.ObservedAt = "", ""
			if reflect.DeepEqual(before, after) {
				batch.Stats.Duplicates++
				batch.Stats.Accepted--
				continue
			}
			plan.Version = old.Version + 1
		} else {
			plan.Version = 1
		}
		payload, e := json.Marshal(plan)
		if e != nil {
			return batch, e
		}
		_, e = tx.ExecContext(ctx, `INSERT INTO planned_events(company_id,source_kind,external_id,version,payload) VALUES($1,$2,$3,$4,$5) ON CONFLICT(company_id,source_kind,external_id) DO UPDATE SET version=EXCLUDED.version,payload=EXCLUDED.payload,updated_at=now()`, batch.CompanyID, plan.SourceKind, plan.ExternalID, plan.Version, payload)
		if e != nil {
			return batch, errors.New("save plan failed")
		}
		freshPlans = append(freshPlans, plan)
	}
	batch.PlannedEvents = freshPlans
	payload, err := json.Marshal(batch)
	if err != nil {
		return batch, err
	}
	if _, err = tx.ExecContext(ctx, `INSERT INTO import_batches(company_id,import_id,payload) VALUES($1,$2,$3)`, batch.CompanyID, batch.ImportID, payload); err != nil {
		return batch, errors.New("save batch failed")
	}
	if err = tx.Commit(); err != nil {
		return batch, errors.New("commit import failed")
	}
	return batch, nil
}

func (p *Postgres) GetPlans(companyID string) ([]contracts.PlannedEvent, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := p.DB.QueryContext(ctx, `SELECT payload FROM planned_events WHERE company_id=$1 ORDER BY source_kind,external_id`, companyID)
	if err != nil {
		return nil, errors.New("read plans failed")
	}
	defer rows.Close()
	out := make([]contracts.PlannedEvent, 0)
	for rows.Next() {
		var raw []byte
		var plan contracts.PlannedEvent
		if rows.Scan(&raw) != nil || json.Unmarshal(raw, &plan) != nil {
			return nil, errors.New("decode plan failed")
		}
		out = append(out, plan)
	}
	return out, rows.Err()
}

func (p *Postgres) GetOperations(companyID string) ([]contracts.Operation, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := p.DB.QueryContext(ctx, `SELECT payload FROM actual_operations WHERE company_id=$1 ORDER BY source_kind,external_id`, companyID)
	if err != nil {
		return nil, errors.New("read operations failed")
	}
	defer rows.Close()
	out := make([]contracts.Operation, 0)
	for rows.Next() {
		var raw []byte
		var op contracts.Operation
		if rows.Scan(&raw) != nil || json.Unmarshal(raw, &op) != nil {
			return nil, errors.New("decode operation failed")
		}
		out = append(out, op)
	}
	return out, rows.Err()
}

func (p *Postgres) RecordRun(companyID, sourceKind string, status int) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	label := "failed"
	if status >= 200 && status < 300 {
		label = "succeeded"
	}
	_, err := p.DB.ExecContext(ctx, `INSERT INTO sync_runs(company_id,source_kind,status,finished_at,error_code) VALUES($1,$2,$3,now(),$4)`, companyID, sourceKind, label, fmt.Sprint(status))
	if err != nil {
		return errors.New("record sync run failed")
	}
	return nil
}

func (p *Postgres) GetRuns(companyID string) ([]SyncRun, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := p.DB.QueryContext(ctx, `SELECT id,company_id,source_kind,error_code,started_at FROM sync_runs WHERE company_id=$1 ORDER BY id DESC LIMIT 100`, companyID)
	if err != nil {
		return nil, errors.New("read sync runs failed")
	}
	defer rows.Close()
	out := make([]SyncRun, 0)
	for rows.Next() {
		var run SyncRun
		var code string
		var at time.Time
		if rows.Scan(&run.ID, &run.CompanyID, &run.SourceKind, &code, &at) != nil {
			return nil, errors.New("decode sync run failed")
		}
		run.Status, _ = strconv.Atoi(code)
		run.StartedAt = at.UTC().Format(time.RFC3339)
		out = append(out, run)
	}
	return out, rows.Err()
}

func (p *Postgres) GetBatches(companyID string) ([]contracts.ImportBatch, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := p.DB.QueryContext(ctx, `SELECT payload FROM import_batches WHERE company_id=$1 ORDER BY id DESC LIMIT 100`, companyID)
	if err != nil {
		return nil, errors.New("read batches failed")
	}
	defer rows.Close()
	out := make([]contracts.ImportBatch, 0)
	for rows.Next() {
		var raw []byte
		var batch contracts.ImportBatch
		if rows.Scan(&raw) != nil || json.Unmarshal(raw, &batch) != nil {
			return nil, errors.New("decode batch failed")
		}
		out = append(out, batch)
	}
	return out, rows.Err()
}

var _ Repository = (*Postgres)(nil)
