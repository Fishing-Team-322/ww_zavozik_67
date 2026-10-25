package store

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

// The liability and all installments commit together under the company lock.
// Cancellation preserves received payments and the liability's audit history.
func syncTaxEvents(ctx context.Context, tx pgx.Tx, cid, id string, d Doc) error {
	if d["status"] == "cancelled" {
		_, e := tx.Exec(ctx, `UPDATE planned_events SET status='cancelled',extra=extra||jsonb_build_object('_revision',COALESCE((extra->>'_revision')::int,0)+1) WHERE company_id=$1 AND extra->>'tax_id'=$2 AND status IN ('expected','missed')`, cid, id)
		return dbError(e)
	}
	var payments []struct {
		Date   string
		Amount float64
	}
	if e := json.Unmarshal(JSON(d["payments"]), &payments); e != nil {
		return e
	}
	for i, p := range payments {
		eventID := uuid.NewSHA1(uuid.NameSpaceOID, []byte(fmt.Sprintf("%s:tax:%s:%d", cid, id, i))).String()
		extra := Doc{"tax_id": id, "source": "tax_calendar", "additional": d["additional"], "source_ref": d["source_ref"], "source_url": d["source_url"], "confirmed": true}
		_, e := tx.Exec(ctx, `INSERT INTO planned_events(id,company_id,source_kind,event_date,amount,direction,title,category,counterparty_name,probability,status,extra) VALUES($1,$2,'tax_calendar',$3,$4,'out',$5,'tax','ФНС',1,'expected',$6) ON CONFLICT(id) DO NOTHING`, eventID, cid, p.Date, p.Amount, d["title"], string(JSON(extra)))
		if e != nil {
			return dbError(e)
		}
	}
	return nil
}
