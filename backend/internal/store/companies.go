package store

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/jackc/pgx/v5"
)

const companyFields = `c.id::text,c.name,c.inn,c.legal_form,c.industry,c.tax_regime,c.reserve::float8,c.default_horizon,
 (SELECT max(op_date)::timestamptz FROM operations WHERE company_id=c.id),c.created_at,c.updated_at`

func scanCompany(row scanner) (c platform.Company, err error) {
	err = row.Scan(&c.ID, &c.Name, &c.INN, &c.LegalForm, &c.Industry, &c.TaxRegime, &c.Reserve, &c.DefaultHorizon, &c.DataAsOf, &c.CreatedAt, &c.UpdatedAt)
	return c, dbError(err)
}
func (p *Postgres) ListCompanies(ctx context.Context, uid string) ([]platform.Company, error) {
	rows, err := p.Pool.Query(ctx, "SELECT "+companyFields+" FROM companies c JOIN memberships m ON m.company_id=c.id WHERE m.user_id=$1 AND m.role='owner' ORDER BY c.created_at,c.id", uid)
	if err != nil {
		return nil, dbError(err)
	}
	defer rows.Close()
	out := []platform.Company{}
	for rows.Next() {
		c, err := scanCompany(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, c)
	}
	return out, dbError(rows.Err())
}
func (p *Postgres) CreateCompany(ctx context.Context, uid string, in platform.Company) (platform.Company, error) {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return in, dbError(err)
	}
	defer tx.Rollback(ctx)
	c, err := scanCompany(tx.QueryRow(ctx, `INSERT INTO companies AS c(name,inn,legal_form,industry,tax_regime,reserve,default_horizon) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING c.id::text,c.name,c.inn,c.legal_form,c.industry,c.tax_regime,c.reserve::float8,c.default_horizon,NULL::timestamptz,c.created_at,c.updated_at`, in.Name, in.INN, in.LegalForm, in.Industry, in.TaxRegime, in.Reserve, in.DefaultHorizon))
	if err != nil {
		return c, err
	}
	if _, err = tx.Exec(ctx, "INSERT INTO memberships(user_id,company_id,role) VALUES($1,$2,'owner')", uid, c.ID); err != nil {
		return c, dbError(err)
	}
	if _, err = tx.Exec(ctx, "INSERT INTO company_state(company_id) VALUES($1)", c.ID); err != nil {
		return c, dbError(err)
	}
	return c, dbError(tx.Commit(ctx))
}
func (p *Postgres) GetCompany(ctx context.Context, uid, id string) (platform.Company, error) {
	return scanCompany(p.Pool.QueryRow(ctx, "SELECT "+companyFields+" FROM companies c JOIN memberships m ON m.company_id=c.id WHERE c.id=$1 AND m.user_id=$2 AND m.role='owner'", id, uid))
}
func (p *Postgres) UpdateCompany(ctx context.Context, uid string, in platform.Company) (platform.Company, error) {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return in, dbError(err)
	}
	defer tx.Rollback(ctx)
	c, err := scanCompany(tx.QueryRow(ctx, `UPDATE companies AS c SET name=$3,inn=$4,legal_form=$5,industry=$6,tax_regime=$7,reserve=$8,default_horizon=$9,updated_at=clock_timestamp()
 WHERE c.id=$1 AND c.updated_at=$10 AND EXISTS(SELECT 1 FROM memberships WHERE company_id=c.id AND user_id=$2 AND role='owner') RETURNING `+companyFields, in.ID, uid, in.Name, in.INN, in.LegalForm, in.Industry, in.TaxRegime, in.Reserve, in.DefaultHorizon, in.UpdatedAt))
	if platform.IsStatus(err, 404) {
		if _, e := p.GetCompany(ctx, uid, in.ID); e == nil {
			return c, platform.Fail(409, "version_conflict", "Компания уже изменена. Обновите данные")
		}
	}
	if err != nil {
		return c, err
	}
	if err = touchCompany(ctx, tx, uid, in.ID); err != nil {
		return c, err
	}
	return c, dbError(tx.Commit(ctx))
}
func (p *Postgres) DeleteCompany(ctx context.Context, uid, id, confirm string) error {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return dbError(err)
	}
	defer tx.Rollback(ctx)
	var name string
	err = tx.QueryRow(ctx, "SELECT c.name FROM companies c JOIN memberships m ON m.company_id=c.id WHERE c.id=$1 AND m.user_id=$2 AND m.role='owner' FOR UPDATE OF c", id, uid).Scan(&name)
	if err != nil {
		return dbError(err)
	}
	if name != confirm {
		return platform.Fail(400, "confirmation_mismatch", "Название компании не совпадает")
	}
	if _, err = tx.Exec(ctx, "DELETE FROM companies WHERE id=$1", id); err != nil {
		return dbError(err)
	}
	return dbError(tx.Commit(ctx))
}
func (p *Postgres) GetState(ctx context.Context, uid, id string) (platform.State, error) {
	var s platform.State
	err := p.Pool.QueryRow(ctx, `SELECT c.id::text,COALESCE(s.version,0),COALESCE(s.data,'{}'::jsonb),COALESCE(s.updated_at,c.created_at)
 FROM companies c JOIN memberships m ON m.company_id=c.id LEFT JOIN company_state s ON s.company_id=c.id WHERE c.id=$1 AND m.user_id=$2 AND m.role='owner'`, id, uid).Scan(&s.CompanyID, &s.Version, &s.Data, &s.UpdatedAt)
	return s, dbError(err)
}
func (p *Postgres) PutState(ctx context.Context, uid, id string, expected int64, data []byte) (platform.State, error) {
	var s platform.State
	if expected < 0 || len(data) > 512*1024 || !json.Valid(data) {
		return s, platform.Fail(400, "invalid_state", "Некорректное состояние компании")
	}
	var object map[string]json.RawMessage
	if err := json.Unmarshal(data, &object); err != nil || object == nil {
		return s, platform.Fail(400, "invalid_state", "Состояние должно быть JSON-объектом")
	}
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return s, dbError(err)
	}
	defer tx.Rollback(ctx)
	// One company row serializes initial inserts, updates and company deletion.
	var companyID string
	err = tx.QueryRow(ctx, "SELECT c.id::text FROM companies c JOIN memberships m ON m.company_id=c.id WHERE c.id=$1 AND m.user_id=$2 AND m.role='owner' FOR UPDATE OF c", id, uid).Scan(&companyID)
	if err != nil {
		return s, dbError(err)
	}
	var version int64
	err = tx.QueryRow(ctx, "SELECT version FROM company_state WHERE company_id=$1", id).Scan(&version)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return s, dbError(err)
	}
	if version != expected {
		return s, platform.Fail(409, "version_conflict", "Данные изменились на другом устройстве. Загрузите актуальную версию")
	}
	err = tx.QueryRow(ctx, `INSERT INTO company_state(company_id,version,data) VALUES($1,$2,$3::jsonb)
 ON CONFLICT(company_id) DO UPDATE SET version=EXCLUDED.version,data=EXCLUDED.data,updated_at=clock_timestamp()
 RETURNING company_id::text,version,data,updated_at`, id, version+1, string(data)).Scan(&s.CompanyID, &s.Version, &s.Data, &s.UpdatedAt)
	if err != nil {
		return s, dbError(err)
	}
	return s, dbError(tx.Commit(ctx))
}
