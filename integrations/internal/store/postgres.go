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

//go:embed migrations/003_marketplace_entries.sql
var migration3 string

//go:embed migrations/004_risk_versions.sql
var migration4 string

//go:embed migrations/005_counterparty_versions.sql
var migration5 string

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
	if _, err := db.ExecContext(ctx, migration3); err != nil {
		db.Close()
		return nil, errors.New("database migration failed")
	}
	if _, err := db.ExecContext(ctx, migration4); err != nil {
		db.Close()
		return nil, errors.New("database migration failed")
	}
	if _, err := db.ExecContext(ctx, migration5); err != nil {
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

func (p *Postgres) SaveMarketplace(companyID string, entries []MarketplaceEntry) (int, int, error) {
	if companyID == "" {
		return 0, 0, errors.New("company_id required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	tx, err := p.DB.BeginTx(ctx, nil)
	if err != nil {
		return 0, 0, errors.New("marketplace transaction failed")
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, companyID); err != nil {
		return 0, 0, errors.New("marketplace lock failed")
	}
	changed, duplicates := 0, 0
	for _, entry := range entries {
		if entry.ExternalID == "" || (entry.SourceKind != "wildberries_finance" && entry.SourceKind != "ozon_finance") || entry.Currency != "RUB" || entry.ForecastEligible {
			return 0, 0, errors.New("invalid marketplace entry")
		}
		var raw []byte
		err := tx.QueryRowContext(ctx, `SELECT payload FROM marketplace_entries WHERE company_id=$1 AND source_kind=$2 AND external_id=$3 FOR UPDATE`, companyID, entry.SourceKind, entry.ExternalID).Scan(&raw)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return 0, 0, errors.New("read marketplace entry failed")
		}
		if err == nil {
			var old MarketplaceEntry
			if json.Unmarshal(raw, &old) != nil {
				return 0, 0, errors.New("invalid stored marketplace entry")
			}
			before, after := old, entry
			before.Version, after.Version = 0, 0
			before.ObservedAt, after.ObservedAt = "", ""
			if reflect.DeepEqual(before, after) {
				duplicates++
				continue
			}
			entry.Version = old.Version + 1
		} else {
			entry.Version = 1
		}
		payload, e := json.Marshal(entry)
		if e != nil {
			return 0, 0, e
		}
		_, e = tx.ExecContext(ctx, `INSERT INTO marketplace_entries(company_id,source_kind,external_id,version,payload) VALUES($1,$2,$3,$4,$5) ON CONFLICT(company_id,source_kind,external_id) DO UPDATE SET version=EXCLUDED.version,payload=EXCLUDED.payload,updated_at=now()`, companyID, entry.SourceKind, entry.ExternalID, entry.Version, payload)
		if e != nil {
			return 0, 0, errors.New("save marketplace entry failed")
		}
		changed++
	}
	if err = tx.Commit(); err != nil {
		return 0, 0, errors.New("commit marketplace entries failed")
	}
	return changed, duplicates, nil
}

func (p *Postgres) GetMarketplace(companyID string) ([]MarketplaceEntry, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := p.DB.QueryContext(ctx, `SELECT payload FROM marketplace_entries WHERE company_id=$1 ORDER BY source_kind,external_id LIMIT 10000`, companyID)
	if err != nil {
		return nil, errors.New("read marketplace entries failed")
	}
	defer rows.Close()
	out := make([]MarketplaceEntry, 0)
	for rows.Next() {
		var raw []byte
		var entry MarketplaceEntry
		if rows.Scan(&raw) != nil || json.Unmarshal(raw, &entry) != nil {
			return nil, errors.New("decode marketplace entry failed")
		}
		out = append(out, entry)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveRisks(companyID string, signals []RiskSignal) (int, int, error) {
	if companyID == "" {
		return 0, 0, errors.New("company_id required")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	tx, err := p.DB.BeginTx(ctx, nil)
	if err != nil {
		return 0, 0, errors.New("risk transaction failed")
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, companyID); err != nil {
		return 0, 0, errors.New("risk lock failed")
	}
	changed, duplicates := 0, 0
	for _, signal := range signals {
		if signal.ExternalID == "" || signal.SourceKind != "fns_debt_snapshot" || len(signal.SubjectINN) != 10 || signal.DatasetAsOf == "" || signal.SourceURL == "" || signal.AmountKopecks < 0 {
			return 0, 0, errors.New("invalid risk signal")
		}
		var raw []byte
		err := tx.QueryRowContext(ctx, `SELECT payload FROM risk_signals WHERE company_id=$1 AND source_kind=$2 AND external_id=$3 FOR UPDATE`, companyID, signal.SourceKind, signal.ExternalID).Scan(&raw)
		if err != nil && !errors.Is(err, sql.ErrNoRows) {
			return 0, 0, errors.New("read risk signal failed")
		}
		if err == nil {
			var old RiskSignal
			if json.Unmarshal(raw, &old) != nil {
				return 0, 0, errors.New("invalid stored risk signal")
			}
			before, after := old, signal
			before.Version, after.Version = 0, 0
			before.RetrievedAt, after.RetrievedAt = "", ""
			if reflect.DeepEqual(before, after) {
				duplicates++
				continue
			}
			signal.Version = old.Version + 1
		} else {
			signal.Version = 1
		}
		payload, e := json.Marshal(signal)
		if e != nil {
			return 0, 0, e
		}
		_, e = tx.ExecContext(ctx, `INSERT INTO risk_signals(company_id,source_kind,external_id,version,payload) VALUES($1,$2,$3,$4,$5) ON CONFLICT(company_id,source_kind,external_id) DO UPDATE SET version=EXCLUDED.version,payload=EXCLUDED.payload,updated_at=now()`, companyID, signal.SourceKind, signal.ExternalID, signal.Version, payload)
		if e != nil {
			return 0, 0, errors.New("save risk signal failed")
		}
		changed++
	}
	if err = tx.Commit(); err != nil {
		return 0, 0, errors.New("commit risks failed")
	}
	return changed, duplicates, nil
}

func (p *Postgres) GetRisks(companyID string) ([]RiskSignal, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := p.DB.QueryContext(ctx, `SELECT payload FROM risk_signals WHERE company_id=$1 ORDER BY source_kind,external_id LIMIT 10000`, companyID)
	if err != nil {
		return nil, errors.New("read risks failed")
	}
	defer rows.Close()
	out := make([]RiskSignal, 0)
	for rows.Next() {
		var raw []byte
		var signal RiskSignal
		if rows.Scan(&raw) != nil || json.Unmarshal(raw, &signal) != nil {
			return nil, errors.New("decode risk signal failed")
		}
		out = append(out, signal)
	}
	return out, rows.Err()
}

func (p *Postgres) SaveCounterparty(companyID string, party Counterparty) (Counterparty, error) {
	if companyID == "" || party.ExternalID == "" || party.SourceKind != "dadata" || party.INN == "" || party.Name == "" || party.CheckedAt == "" {
		return party, errors.New("invalid counterparty")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	tx, err := p.DB.BeginTx(ctx, nil)
	if err != nil {
		return party, errors.New("counterparty transaction failed")
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, companyID); err != nil {
		return party, errors.New("counterparty lock failed")
	}
	var raw []byte
	err = tx.QueryRowContext(ctx, `SELECT payload FROM counterparties WHERE company_id=$1 AND source_kind=$2 AND external_id=$3 FOR UPDATE`, companyID, party.SourceKind, party.ExternalID).Scan(&raw)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return party, errors.New("read counterparty failed")
	}
	if err == nil {
		var old Counterparty
		if json.Unmarshal(raw, &old) != nil {
			return party, errors.New("invalid stored counterparty")
		}
		before, after := old, party
		before.Version, after.Version = 0, 0
		if reflect.DeepEqual(before, after) {
			return old, nil
		}
		party.Version = old.Version + 1
	} else {
		party.Version = 1
	}
	payload, e := json.Marshal(party)
	if e != nil {
		return party, e
	}
	_, e = tx.ExecContext(ctx, `INSERT INTO counterparties(company_id,source_kind,external_id,version,payload) VALUES($1,$2,$3,$4,$5) ON CONFLICT(company_id,source_kind,external_id) DO UPDATE SET version=EXCLUDED.version,payload=EXCLUDED.payload,updated_at=now()`, companyID, party.SourceKind, party.ExternalID, party.Version, payload)
	if e != nil {
		return party, errors.New("save counterparty failed")
	}
	if err = tx.Commit(); err != nil {
		return party, errors.New("commit counterparty failed")
	}
	return party, nil
}

func (p *Postgres) GetCounterparties(companyID string) ([]Counterparty, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	rows, err := p.DB.QueryContext(ctx, `SELECT payload FROM counterparties WHERE company_id=$1 ORDER BY source_kind,external_id LIMIT 10000`, companyID)
	if err != nil {
		return nil, errors.New("read counterparties failed")
	}
	defer rows.Close()
	out := make([]Counterparty, 0)
	for rows.Next() {
		var raw []byte
		var party Counterparty
		if rows.Scan(&raw) != nil || json.Unmarshal(raw, &party) != nil {
			return nil, errors.New("decode counterparty failed")
		}
		out = append(out, party)
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
