package store

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fnsregistry"
)

type RegistryStore interface {
	SaveRegistry(context.Context, string, fnsregistry.Record) (fnsregistry.Record, string, error)
	GetRegistry(context.Context, string, string) ([]fnsregistry.Record, error)
	RegistryHistory(context.Context, string, string) ([]fnsregistry.Record, error)
}

func registryHash(r fnsregistry.Record) (string, error) {
	r.RetrievedAt = ""
	r.Version = 0
	b, err := json.Marshal(r)
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:]), nil
}

func (p *Postgres) SaveRegistry(ctx context.Context, company string, r fnsregistry.Record) (fnsregistry.Record, string, error) {
	if company == "" || r.INN == "" || r.OGRN == "" || r.ActualAt == "" || (r.Source != "FNS_EGRUL" && r.Source != "FNS_EGRIP") {
		return r, "", errors.New("invalid registry record")
	}
	hash, err := registryHash(r)
	if err != nil {
		return r, "", err
	}
	tx, err := p.DB.BeginTx(ctx, nil)
	if err != nil {
		return r, "", err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, `SELECT pg_advisory_xact_lock(hashtext($1))`, company+":"+r.Source+":"+r.OGRN); err != nil {
		return r, "", err
	}
	var oldHash string
	var oldVersion int64
	var oldDate time.Time
	var oldPayload []byte
	err = tx.QueryRowContext(ctx, `SELECT content_hash,version,actual_at,payload FROM fns_registry_current WHERE company_id=$1 AND source_kind=$2 AND ogrn=$3 FOR UPDATE`, company, r.Source, r.OGRN).Scan(&oldHash, &oldVersion, &oldDate, &oldPayload)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return r, "", err
	}
	if err == nil && oldHash == hash {
		var old fnsregistry.Record
		if json.Unmarshal(oldPayload, &old) != nil {
			return r, "", errors.New("corrupt registry record")
		}
		return old, "duplicate", nil
	}
	if err == nil && r.ActualAt < oldDate.Format("2006-01-02") {
		return r, "outdated", nil
	}
	r.Version = oldVersion + 1
	if err == sql.ErrNoRows {
		r.Version = 1
	}
	payload, err := json.Marshal(r)
	if err != nil {
		return r, "", err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO fns_registry_history(company_id,source_kind,ogrn,inn,actual_at,content_hash,payload) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT DO NOTHING`, company, r.Source, r.OGRN, r.INN, r.ActualAt, hash, payload)
	if err != nil {
		return r, "", err
	}
	_, err = tx.ExecContext(ctx, `INSERT INTO fns_registry_current(company_id,source_kind,ogrn,inn,actual_at,content_hash,version,payload) VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(company_id,source_kind,ogrn) DO UPDATE SET inn=EXCLUDED.inn,actual_at=EXCLUDED.actual_at,content_hash=EXCLUDED.content_hash,version=EXCLUDED.version,payload=EXCLUDED.payload,updated_at=now()`, company, r.Source, r.OGRN, r.INN, r.ActualAt, hash, r.Version, payload)
	if err != nil {
		return r, "", err
	}
	if err = tx.Commit(); err != nil {
		return r, "", err
	}
	return r, "updated", nil
}

func (p *Postgres) GetRegistry(ctx context.Context, company, id string) ([]fnsregistry.Record, error) {
	rows, err := p.DB.QueryContext(ctx, `SELECT payload FROM fns_registry_current WHERE company_id=$1 AND (inn=$2 OR ogrn=$2) ORDER BY actual_at DESC LIMIT 50`, company, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanRegistry(rows)
}
func (p *Postgres) RegistryHistory(ctx context.Context, company, id string) ([]fnsregistry.Record, error) {
	rows, err := p.DB.QueryContext(ctx, `SELECT payload FROM fns_registry_history WHERE company_id=$1 AND (inn=$2 OR ogrn=$2) ORDER BY id DESC LIMIT 100`, company, id)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanRegistry(rows)
}
func scanRegistry(rows *sql.Rows) ([]fnsregistry.Record, error) {
	out := make([]fnsregistry.Record, 0)
	for rows.Next() {
		var raw []byte
		var r fnsregistry.Record
		if err := rows.Scan(&raw); err != nil {
			return nil, err
		}
		if err := json.Unmarshal(raw, &r); err != nil {
			return nil, err
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
