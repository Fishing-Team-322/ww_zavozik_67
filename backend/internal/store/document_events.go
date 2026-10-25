package store

import (
	"context"
	"math"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
)

func DocumentEventID(cid, id string, index int) string {
	return uuid.NewSHA1(uuid.NameSpaceOID, JSON([]any{cid, id, index})).String()
}

func contractEntries(d Doc) []Doc {
	entries := []Doc{}
	switch list := d["schedule"].(type) {
	case []any:
		for _, value := range list {
			if entry, ok := value.(map[string]any); ok {
				entries = append(entries, Doc(entry))
			}
		}
	case []Doc:
		entries = list
	}
	return entries
}

// A metadata edit must not reopen a bank-settled contract installment.
// Paid financial terms cannot be silently rewritten by an old editor snapshot.
func preserveContractReceipts(ctx context.Context, tx pgx.Tx, cid, id string, d Doc) error {
	rows, err := tx.Query(ctx, "SELECT id::text,event_date::text,amount::float8,direction FROM planned_events WHERE company_id=$1 AND extra->>'document_id'=$2 AND matched_operation_id IS NOT NULL", cid, id)
	if err != nil {
		return dbError(err)
	}
	defer rows.Close()
	entries := contractEntries(d)
	for rows.Next() {
		var eventID, date, direction string
		var amount float64
		if err = rows.Scan(&eventID, &date, &amount, &direction); err != nil {
			return dbError(err)
		}
		found := false
		for i, entry := range entries {
			if DocumentEventID(cid, id, i) != eventID {
				continue
			}
			value, _ := entry["amount"].(float64)
			if entry["date"] != date || math.Round(value*100) != math.Round(amount*100) || d["direction"] != direction {
				return platform.Fail(409, "settled_installment", "Оплаченный по выписке платёж нельзя изменить. Добавьте новое обязательство для корректировки.")
			}
			entry["status"] = "received"
			found = true
			break
		}
		if !found {
			return platform.Fail(409, "settled_installment", "Нельзя удалить оплаченный по выписке платёж из графика договора")
		}
	}
	return dbError(rows.Err())
}

func ApplyContractReceipt(ctx context.Context, tx pgx.Tx, cid, id, eventID string) error {
	var raw []byte
	if err := tx.QueryRow(ctx, "SELECT data FROM product_documents WHERE id::text=$1 AND company_id=$2 AND kind='contract' FOR UPDATE", id, cid).Scan(&raw); err != nil {
		return dbError(err)
	}
	d := Decode(raw)
	for i, entry := range contractEntries(d) {
		if DocumentEventID(cid, id, i) != eventID {
			continue
		}
		entry["status"] = "received"
		d["_revision"] = revision(d) + 1
		_, err := tx.Exec(ctx, "UPDATE product_documents SET data=$3,updated_at=clock_timestamp() WHERE id::text=$1 AND company_id=$2", id, cid, string(JSON(d)))
		return dbError(err)
	}
	return platform.Fail(409, "schedule_changed", "График договора изменился. Проверьте платёж.")
}

func syncDocumentEvents(ctx context.Context, tx pgx.Tx, cid, kind, id string, d Doc) error {
	// Documents and their calendar projections are committed in the same transaction.
	matches := map[string]string{}
	rows, err := tx.Query(ctx, "SELECT id::text,matched_operation_id FROM planned_events WHERE company_id=$1 AND extra->>'document_id'=$2 AND matched_operation_id IS NOT NULL", cid, id)
	if err != nil {
		return dbError(err)
	}
	for rows.Next() {
		var eventID, operation string
		if err = rows.Scan(&eventID, &operation); err != nil {
			rows.Close()
			return dbError(err)
		}
		matches[eventID] = operation
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return dbError(err)
	}
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
		if status == "received" && str("replaces_event_id") != "" {
			if _, err := tx.Exec(ctx, `UPDATE planned_events SET status='received',extra=extra||jsonb_build_object('_revision',COALESCE((extra->>'_revision')::int,0)+1,'replacement_settled_by',$3::text) WHERE company_id=$1 AND id::text=$2`, cid, str("replaces_event_id"), id); err != nil {
				return dbError(err)
			}
		}
	} else {
		entries = contractEntries(d)
	}
	additional, _ := d["additional"].(bool)
	for i, entry := range entries {
		eventID := DocumentEventID(cid, id, i)
		extra := Doc{"document_id": id, "document_kind": kind, "additional": additional, "counterparty_inn": d["counterparty_inn"], "replaces_event_id": d["replaces_event_id"]}
		_, e := tx.Exec(ctx, `INSERT INTO planned_events(id,company_id,source_kind,event_date,amount,direction,title,category,counterparty_name,probability,status,extra,matched_operation_id) VALUES($1,$2,$3,$4,$5,$6,$7,'other',$8,1,$9,$10,NULLIF($11,''))`, eventID, cid, kind, entry["date"], entry["amount"], direction, str("number"), str("counterparty_name"), entry["status"], string(JSON(extra)), matches[eventID])
		if e != nil {
			return dbError(e)
		}
	}
	return nil
}
