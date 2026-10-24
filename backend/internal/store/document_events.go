package store

import (
	"context"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func syncDocumentEvents(ctx context.Context, tx pgx.Tx, cid, kind, id string, d Doc) error {
	// Documents and their calendar projections are committed in the same transaction.
	if _, e := tx.Exec(ctx, "DELETE FROM planned_events WHERE company_id=$1 AND extra->>'document_id'=$2", cid, id); e != nil {
		return dbError(e)
	}
	str := func(k string) string { v, _ := d[k].(string); return v }
	num := func(k string) float64 { v, _ := d[k].(float64); return v }
	entries := []Doc{}
	direction := str("direction")
	if kind == "invoice" {
		if direction == "issued" {
			direction = "in"
		} else {
			direction = "out"
		}
		amount := num("amount") - num("paid_amount")
		status := "expected"
		if amount <= 0 {
			amount = num("amount")
			status = "received"
		}
		entries = append(entries, Doc{"date": d["expected_pay_at"], "amount": amount, "status": status})
	} else {
		if list, ok := d["schedule"].([]any); ok {
			for _, v := range list {
				if entry, yes := v.(map[string]any); yes {
					entries = append(entries, Doc(entry))
				}
			}
		}
	}
	additional, _ := d["additional"].(bool)
	for i, entry := range entries {
		key := string(JSON([]any{cid, id, i}))
		eventID := uuid.NewSHA1(uuid.NameSpaceOID, []byte(key)).String()
		extra := Doc{"document_id": id, "document_kind": kind, "additional": additional}
		_, e := tx.Exec(ctx, `INSERT INTO planned_events(id,company_id,source_kind,event_date,amount,direction,title,category,counterparty_name,probability,status,extra) VALUES($1,$2,$3,$4,$5,$6,$7,'other',$8,1,$9,$10)`, eventID, cid, kind, entry["date"], entry["amount"], direction, str("number"), str("counterparty_name"), entry["status"], string(JSON(extra)))
		if e != nil {
			return dbError(e)
		}
	}
	return nil
}
