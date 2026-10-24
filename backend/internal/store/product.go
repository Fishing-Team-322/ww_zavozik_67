package store

import (
	"context"
	"encoding/json"
	"errors"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/jackc/pgx/v5"
)

type Doc map[string]any

func JSON(v any) []byte   { b, _ := json.Marshal(v); return b }
func Decode(b []byte) Doc { var d Doc; _ = json.Unmarshal(b, &d); return d }

var productTables = map[string]string{"operation": "operations", "event": "planned_events", "recurring": "recurring_patterns", "source": "sources", "scenario": "scenarios", "alert": "alerts"}

func productQuery(kind string) (string, error) {
	if table, ok := productTables[kind]; ok {
		return "SELECT t.extra||(to_jsonb(t)-'extra'-'config'-'config_secret') AS doc FROM " + table + " t", nil
	}
	switch kind {
	case "invoice", "contract", "action", "signal", "import", "model_quality", "classifier_quality", "drift":
		return "SELECT data||jsonb_build_object('id',id,'company_id',company_id,'created_at',created_at,'updated_at',updated_at) AS doc FROM product_documents t WHERE kind='" + kind + "'", nil
	}
	return "", errors.New("unknown resource kind")
}
func (p *Postgres) ProductList(ctx context.Context, uid, cid, kind string) ([]Doc, error) {
	if _, err := p.GetCompany(ctx, uid, cid); err != nil {
		return nil, err
	}
	query, err := productQuery(kind)
	if err != nil {
		return nil, err
	}
	sep := " WHERE "
	if productTables[kind] == "" {
		sep = " AND "
	}
	rows, err := p.Pool.Query(ctx, query+sep+"t.company_id=$1 ORDER BY t.id LIMIT 100001", cid)
	if err != nil {
		return nil, dbError(err)
	}
	defer rows.Close()
	out := []Doc{}
	for rows.Next() {
		var b []byte
		if err = rows.Scan(&b); err != nil {
			return nil, dbError(err)
		}
		out = append(out, Decode(b))
	}
	if len(out) > 100000 {
		return nil, platform.Fail(413, "dataset_too_large", "Слишком большой набор данных для одного расчёта")
	}
	return out, dbError(rows.Err())
}
func (p *Postgres) ProductGet(ctx context.Context, uid, kind, id string) (Doc, error) {
	query, err := productQuery(kind)
	if err != nil {
		return nil, err
	}
	sep := " WHERE "
	if productTables[kind] == "" {
		sep = " AND "
	}
	rows, err := p.Pool.Query(ctx, query+sep+`t.id::text=$1 AND EXISTS(SELECT 1 FROM memberships m WHERE m.company_id=t.company_id AND m.user_id=$2 AND m.role='owner') LIMIT 2`, id, uid)
	if err != nil {
		return nil, dbError(err)
	}
	defer rows.Close()
	docs := []Doc{}
	for rows.Next() {
		var b []byte
		if err = rows.Scan(&b); err != nil {
			return nil, dbError(err)
		}
		docs = append(docs, Decode(b))
	}
	if err = rows.Err(); err != nil {
		return nil, dbError(err)
	}
	if len(docs) == 0 {
		return nil, platform.ErrNotFound
	}
	if len(docs) > 1 {
		return nil, platform.Fail(409, "ambiguous_id", "Идентификатор операции неоднозначен")
	}
	return docs[0], nil
}
func lockCompany(ctx context.Context, tx pgx.Tx, uid, cid string) error {
	var id string
	return dbError(tx.QueryRow(ctx, `SELECT c.id::text FROM companies c JOIN memberships m ON m.company_id=c.id JOIN users u ON u.id=m.user_id WHERE c.id=$1 AND m.user_id=$2 AND m.role='owner' AND u.status='active' FOR UPDATE OF c`, cid, uid).Scan(&id))
}
func touchCompany(ctx context.Context, tx pgx.Tx, uid, cid string) error {
	if _, err := tx.Exec(ctx, "UPDATE companies SET data_revision=data_revision+1,updated_at=clock_timestamp() WHERE id=$1", cid); err != nil {
		return dbError(err)
	}
	_, err := tx.Exec(ctx, `INSERT INTO product_jobs(company_id,actor_id,kind) VALUES($1,$2,'recompute') ON CONFLICT(company_id) WHERE kind='recompute' AND status='queued' DO NOTHING`, cid, uid)
	return dbError(err)
}
func revision(d Doc) int64 { n, _ := d["_revision"].(float64); return int64(n) }
func (p *Postgres) ProductSave(ctx context.Context, uid, cid, kind, id string, d Doc, create bool) (Doc, error) {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return nil, dbError(err)
	}
	defer tx.Rollback(ctx)
	if err = lockCompany(ctx, tx, uid, cid); err != nil {
		return nil, err
	}
	if create {
		query, e := productQuery(kind)
		if e != nil {
			return nil, e
		}
		var raw []byte
		e = tx.QueryRow(ctx, "SELECT doc FROM ("+query+") existing WHERE doc->>'id'=$1 AND doc->>'company_id'=$2", id, cid).Scan(&raw)
		if e == nil {
			return Decode(raw), nil
		} // Derived IDs are idempotent and must never overwrite an edit.
		if !errors.Is(e, pgx.ErrNoRows) {
			return nil, dbError(e)
		}
	}
	if !create {
		var old []byte
		table := productTables[kind]
		if table != "" {
			err = tx.QueryRow(ctx, "SELECT to_jsonb(t)||t.extra FROM "+table+" t WHERE id::text=$1 AND company_id=$2 FOR UPDATE", id, cid).Scan(&old)
		} else {
			err = tx.QueryRow(ctx, "SELECT data FROM product_documents WHERE id::text=$1 AND company_id=$2 AND kind=$3 FOR UPDATE", id, cid, kind).Scan(&old)
		}
		if err != nil {
			return nil, dbError(err)
		}
		if revision(Decode(old)) != revision(d) {
			return nil, platform.Fail(409, "version_conflict", "Запись уже изменена. Обновите данные")
		}
	}
	d["_revision"] = revision(d) + 1
	if err = writeProduct(ctx, tx, cid, kind, id, d); err != nil {
		return nil, err
	}
	if kind != "alert" && kind != "signal" && kind != "action" && kind != "import" {
		if err = touchCompany(ctx, tx, uid, cid); err != nil {
			return nil, err
		}
	}
	_, err = tx.Exec(ctx, "INSERT INTO audit_log(user_id,company_id,action) VALUES($1,$2,$3)", uid, cid, kind+"_saved")
	if err != nil {
		return nil, dbError(err)
	}
	if err = tx.Commit(ctx); err != nil {
		return nil, dbError(err)
	}
	return p.ProductGet(ctx, uid, kind, id)
}
func writeProduct(ctx context.Context, tx pgx.Tx, cid, kind, id string, d Doc) error {
	sealed := d["_sealed_config"]
	delete(d, "_sealed_config")
	raw := string(JSON(d))
	var err error
	switch kind {
	case "event":
		_, err = tx.Exec(ctx, `INSERT INTO planned_events(id,company_id,source_kind,event_date,amount,direction,title,category,counterparty_name,probability,status,extra)
 VALUES($1,$2,$3::jsonb->>'source',($3::jsonb->>'date')::date,($3::jsonb->>'amount')::numeric,$3::jsonb->>'direction',$3::jsonb->>'title',$3::jsonb->>'category',$3::jsonb->>'counterparty_name',($3::jsonb->>'probability')::float8,$3::jsonb->>'status',$3)
 ON CONFLICT(id) DO UPDATE SET event_date=EXCLUDED.event_date,amount=EXCLUDED.amount,direction=EXCLUDED.direction,title=EXCLUDED.title,category=EXCLUDED.category,counterparty_name=EXCLUDED.counterparty_name,probability=EXCLUDED.probability,status=EXCLUDED.status,extra=EXCLUDED.extra`, id, cid, raw)
	case "recurring":
		_, err = tx.Exec(ctx, `INSERT INTO recurring_patterns(id,company_id,title,category,direction,counterparty_name,period,day_of_month,amount,amount_spread,next_date,confirmed,active,extra)
 VALUES($1,$2,$3::jsonb->>'title',$3::jsonb->>'category',$3::jsonb->>'direction',$3::jsonb->>'counterparty_name',$3::jsonb->>'period',($3::jsonb->>'day_of_month')::int,($3::jsonb->>'amount')::numeric,COALESCE(($3::jsonb->>'amount_spread')::numeric,0),($3::jsonb->>'next_date')::date,($3::jsonb->>'confirmed')::boolean,($3::jsonb->>'active')::boolean,$3)
 ON CONFLICT(id) DO UPDATE SET title=EXCLUDED.title,amount=EXCLUDED.amount,period=EXCLUDED.period,day_of_month=EXCLUDED.day_of_month,confirmed=EXCLUDED.confirmed,active=EXCLUDED.active,next_date=EXCLUDED.next_date,extra=EXCLUDED.extra,updated_at=clock_timestamp()`, id, cid, raw)
	case "source":
		_, err = tx.Exec(ctx, `INSERT INTO sources(id,company_id,kind,title,status,enabled,extra,config_secret) VALUES($1,$2,$3::jsonb->>'kind',$3::jsonb->>'title',$3::jsonb->>'status',($3::jsonb->>'enabled')::boolean,$3,$4)
 ON CONFLICT(id) DO UPDATE SET title=EXCLUDED.title,status=EXCLUDED.status,enabled=EXCLUDED.enabled,extra=EXCLUDED.extra,config_secret=COALESCE(EXCLUDED.config_secret,sources.config_secret)`, id, cid, raw, sealed)
	case "scenario":
		_, err = tx.Exec(ctx, `INSERT INTO scenarios(id,company_id,title,steps,extra) VALUES($1,$2,$3::jsonb->>'title',$3::jsonb->'steps',$3) ON CONFLICT(id) DO UPDATE SET title=EXCLUDED.title,steps=EXCLUDED.steps,extra=EXCLUDED.extra`, id, cid, raw)
	case "alert":
		_, err = tx.Exec(ctx, `INSERT INTO alerts(id,company_id,severity,title,body,kind,read,extra) VALUES($1,$2,$3::jsonb->>'severity',$3::jsonb->>'title',$3::jsonb->>'body',$3::jsonb->>'kind',COALESCE(($3::jsonb->>'read')::boolean,false),$3)
 ON CONFLICT(id) DO UPDATE SET read=EXCLUDED.read,extra=EXCLUDED.extra`, id, cid, raw)
	case "operation":
		_, err = tx.Exec(ctx, `UPDATE operations SET category=$3::jsonb->>'category',category_method='user',is_internal=($3::jsonb->>'is_internal')::boolean,extra=$3 WHERE id=$1 AND company_id=$2`, id, cid, raw)
	default:
		_, err = tx.Exec(ctx, `INSERT INTO product_documents(id,company_id,kind,data) VALUES($1,$2,$3,$4) ON CONFLICT(id) DO UPDATE SET data=EXCLUDED.data,updated_at=clock_timestamp()`, id, cid, kind, raw)
	}
	if err != nil {
		return dbError(err)
	}
	if kind == "invoice" || kind == "contract" {
		return syncDocumentEvents(ctx, tx, cid, kind, id, d)
	}
	if kind == "recurring" {
		_, err = tx.Exec(ctx, "DELETE FROM planned_events WHERE company_id=$1 AND extra->>'recurring_id'=$2 AND event_date>=current_date AND status='expected' AND COALESCE((extra->>'user_override')::boolean,false)=false", cid, id)
	}
	if kind == "operation" {
		_, err = tx.Exec(ctx, "INSERT INTO category_corrections(company_id,operation_id,category) VALUES($1,$2,$3)", cid, id, d["category"])
	}
	return dbError(err)
}
func (p *Postgres) ProductDelete(ctx context.Context, uid, cid, kind, id string) error {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return dbError(err)
	}
	defer tx.Rollback(ctx)
	if err = lockCompany(ctx, tx, uid, cid); err != nil {
		return err
	}
	table := productTables[kind]
	var n int64
	if table != "" {
		tag, e := tx.Exec(ctx, "DELETE FROM "+table+" WHERE id::text=$1 AND company_id=$2", id, cid)
		err = e
		n = tag.RowsAffected()
	} else {
		tag, e := tx.Exec(ctx, "DELETE FROM product_documents WHERE id::text=$1 AND company_id=$2 AND kind=$3", id, cid, kind)
		err = e
		n = tag.RowsAffected()
	}
	if err != nil {
		return dbError(err)
	}
	if n == 0 {
		return platform.ErrNotFound
	}
	if kind == "invoice" || kind == "contract" {
		if _, err = tx.Exec(ctx, "DELETE FROM planned_events WHERE company_id=$1 AND extra->>'document_id'=$2", cid, id); err != nil {
			return dbError(err)
		}
	}
	if kind == "recurring" {
		if _, err = tx.Exec(ctx, "DELETE FROM planned_events WHERE company_id=$1 AND extra->>'recurring_id'=$2 AND status='expected' AND COALESCE((extra->>'user_override')::boolean,false)=false", cid, id); err != nil {
			return dbError(err)
		}
	}
	if err = touchCompany(ctx, tx, uid, cid); err != nil {
		return err
	}
	return dbError(tx.Commit(ctx))
}
func (p *Postgres) ProductJob(ctx context.Context, uid, cid, kind string, payload Doc) (Doc, error) {
	var id string
	err := p.Pool.QueryRow(ctx, `INSERT INTO product_jobs(actor_id,company_id,kind,payload) VALUES($1,NULLIF($2,'')::uuid,$3,$4) RETURNING id::text`, uid, cid, kind, string(JSON(payload))).Scan(&id)
	if err != nil {
		return nil, dbError(err)
	}
	return p.GetProductJob(ctx, uid, id, false)
}
func (p *Postgres) GetProductJob(ctx context.Context, uid, id string, admin bool) (Doc, error) {
	var raw []byte
	err := p.Pool.QueryRow(ctx, `SELECT jsonb_build_object('id',id,'company_id',company_id,'kind',kind,'status',status,'progress',progress,'error',error,'result_ref',CASE WHEN result IS NULL THEN NULL ELSE result->>'result_ref' END,'result',result) FROM product_jobs WHERE id::text=$1 AND (actor_id=$2 OR $3)`, id, uid, admin).Scan(&raw)
	return Decode(raw), dbError(err)
}
func (p *Postgres) Audit(ctx context.Context, uid, cid, action string, detail Doc) error {
	_, err := p.Pool.Exec(ctx, "INSERT INTO audit_log(user_id,company_id,action,detail) VALUES($1,NULLIF($2,'')::uuid,$3,$4)", uid, cid, action, string(JSON(detail)))
	return dbError(err)
}
func (p *Postgres) QueueRecompute(ctx context.Context, uid, cid string) error {
	tx, e := p.Pool.Begin(ctx)
	if e != nil {
		return dbError(e)
	}
	defer tx.Rollback(ctx)
	if e = lockCompany(ctx, tx, uid, cid); e != nil {
		return e
	}
	if e = touchCompany(ctx, tx, uid, cid); e != nil {
		return e
	}
	return dbError(tx.Commit(ctx))
}

type ProductJob struct {
	ID, UserID, CompanyID, Kind string
	Payload                     Doc
	Attempts                    int
}

func (p *Postgres) ClaimProductJob(ctx context.Context) (ProductJob, error) {
	var j ProductJob
	var b []byte
	err := p.Pool.QueryRow(ctx, `UPDATE product_jobs SET status='running',locked_at=now(),attempts=attempts+1 WHERE id=(SELECT id FROM product_jobs WHERE status='queued' OR (status='running' AND locked_at<now()-interval '5 minutes') ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
 RETURNING id::text,actor_id::text,COALESCE(company_id::text,''),kind,payload,attempts`).Scan(&j.ID, &j.UserID, &j.CompanyID, &j.Kind, &b, &j.Attempts)
	j.Payload = Decode(b)
	return j, dbError(err)
}
func (p *Postgres) FinishProductJob(ctx context.Context, j ProductJob, result Doc, jobErr error) error {
	state := "done"
	var message *string
	if jobErr != nil {
		state = "failed"
		s := "Не удалось выполнить задание"
		var api *platform.Error
		if errors.As(jobErr, &api) {
			s = api.Message
		}
		message = &s
	}
	_, err := p.Pool.Exec(ctx, "UPDATE product_jobs SET status=$2,progress=1,result=$3,error=$4,finished_at=now() WHERE id=$1 AND attempts=$5", j.ID, state, string(JSON(result)), message, j.Attempts)
	return dbError(err)
}
func (p *Postgres) ProductRevision(ctx context.Context, cid string) (int64, error) {
	var n int64
	err := p.Pool.QueryRow(ctx, "SELECT data_revision FROM companies WHERE id=$1", cid).Scan(&n)
	return n, dbError(err)
}
func (p *Postgres) ExpireProductJobs(ctx context.Context) error {
	_, err := p.Pool.Exec(ctx, "UPDATE product_jobs SET status='failed',error='Задание прервано после нескольких попыток',finished_at=now() WHERE status='running' AND locked_at<now()-interval '5 minutes' AND attempts>=3")
	return dbError(err)
}
