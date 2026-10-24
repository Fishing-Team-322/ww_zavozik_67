package store

import (
	"context"
	"math"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/jackc/pgx/v5"
)

// RemoveSourceSettlements runs under the caller's company lock, immediately
// before deleting source operations in the same transaction. Manual payment
// amounts and receipts backed by other sources remain intact.
func RemoveSourceSettlements(ctx context.Context, tx pgx.Tx, cid, sourceID string) error {
	rows, err := tx.Query(ctx, `SELECT s.event_id::text,s.source_kind,COALESCE(s.document_id,''),o.amount::float8
	 FROM operation_settlements s JOIN operations o ON o.company_id=s.company_id AND o.id=s.operation_id
	 WHERE o.company_id=$1 AND o.source_id=$2
	 UNION ALL
	 SELECT e.id::text,e.source_kind,COALESCE(e.extra->>'document_id',''),o.amount::float8
	 FROM planned_events e JOIN operations o ON o.company_id=e.company_id AND o.id=e.matched_operation_id
	 WHERE o.company_id=$1 AND o.source_id=$2 AND NOT EXISTS
	 (SELECT 1 FROM operation_settlements s WHERE s.company_id=o.company_id AND s.operation_id=o.id)`, cid, sourceID)
	if err != nil {
		return dbError(err)
	}
	type receipt struct {
		event, kind, document string
		amount                float64
	}
	receipts := []receipt{}
	eventIDs := []string{}
	invoiceAmounts := map[string]float64{}
	contracts := map[string]map[string]bool{}
	for rows.Next() {
		var r receipt
		if err = rows.Scan(&r.event, &r.kind, &r.document, &r.amount); err != nil {
			rows.Close()
			return dbError(err)
		}
		receipts = append(receipts, r)
		eventIDs = append(eventIDs, r.event)
		if r.kind == "invoice" && r.document != "" {
			invoiceAmounts[r.document] += r.amount
		}
		if r.kind == "contract" && r.document != "" {
			if contracts[r.document] == nil {
				contracts[r.document] = map[string]bool{}
			}
			contracts[r.document][r.event] = true
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return dbError(err)
	}
	if len(receipts) == 0 {
		return nil
	}
	remaining := map[string]string{}
	invoiceDates := map[string]string{}
	rows, err = tx.Query(ctx, `SELECT s.event_id::text,o.id,o.op_date::text,s.source_kind,COALESCE(s.document_id,'')
	 FROM operation_settlements s JOIN operations o ON o.company_id=s.company_id AND o.id=s.operation_id
	 WHERE s.company_id=$1 AND s.event_id=ANY($3::uuid[]) AND o.source_id IS DISTINCT FROM $2::uuid
	 ORDER BY o.op_date,s.matched_at,o.id`, cid, sourceID, eventIDs)
	if err != nil {
		return dbError(err)
	}
	for rows.Next() {
		var event, operation, date, kind, document string
		if err = rows.Scan(&event, &operation, &date, &kind, &document); err != nil {
			rows.Close()
			return dbError(err)
		}
		remaining[event] = operation
		if kind == "invoice" {
			invoiceDates[document] = date
		}
	}
	err = rows.Err()
	rows.Close()
	if err != nil {
		return dbError(err)
	}
	seen := map[string]bool{}
	for _, r := range receipts {
		if seen[r.event] {
			continue
		}
		seen[r.event] = true
		_, err = tx.Exec(ctx, `UPDATE planned_events e SET matched_operation_id=NULLIF($3,''),
		 status=CASE WHEN status='received' AND $3='' THEN
		  CASE WHEN source_kind='tax_calendar' AND EXISTS (SELECT 1 FROM product_documents d WHERE d.company_id=e.company_id AND d.id::text=e.extra->>'tax_id' AND d.kind='tax' AND d.data->>'status'='cancelled') THEN 'cancelled' ELSE 'expected' END
		  ELSE status END,
		 extra=extra||jsonb_build_object('_revision',COALESCE((extra->>'_revision')::int,0)+1)
		 WHERE company_id=$1 AND id=$2`, cid, r.event, remaining[r.event])
		if err != nil {
			return dbError(err)
		}
	}
	for id, removed := range invoiceAmounts {
		var raw []byte
		err = tx.QueryRow(ctx, "SELECT data FROM product_documents WHERE company_id=$1 AND id::text=$2 AND kind='invoice' FOR UPDATE", cid, id).Scan(&raw)
		if err == pgx.ErrNoRows {
			continue
		}
		if err != nil {
			return dbError(err)
		}
		d := Decode(raw)
		paid, _ := d["paid_amount"].(float64)
		total, _ := d["amount"].(float64)
		due, _ := d["due_at"].(string)
		paid = math.Max(0, math.Round((paid-removed)*100)/100)
		d["paid_amount"], d["paid_at"] = paid, nil
		if dt := invoiceDates[id]; paid > 0 && dt != "" {
			d["paid_at"] = dt
		}
		switch {
		case paid >= total:
			d["status"] = "paid"
		case paid > 0:
			d["status"] = "partial"
		case due < time.Now().UTC().Format(domain.DateLayout):
			d["status"] = "overdue"
		default:
			d["status"] = "open"
		}
		d["_revision"] = revision(d) + 1
		if _, err = tx.Exec(ctx, "UPDATE product_documents SET data=$3,updated_at=clock_timestamp() WHERE company_id=$1 AND id::text=$2", cid, id, string(JSON(d))); err != nil {
			return dbError(err)
		}
		if err = syncDocumentEvents(ctx, tx, cid, "invoice", id, d); err != nil {
			return err
		}
	}
	for id, events := range contracts {
		var raw []byte
		err = tx.QueryRow(ctx, "SELECT data FROM product_documents WHERE company_id=$1 AND id::text=$2 AND kind='contract' FOR UPDATE", cid, id).Scan(&raw)
		if err == pgx.ErrNoRows {
			continue
		}
		if err != nil {
			return dbError(err)
		}
		d := Decode(raw)
		changed := false
		for i, entry := range contractEntries(d) {
			event := DocumentEventID(cid, id, i)
			if events[event] && remaining[event] == "" && entry["status"] == "received" {
				entry["status"] = "expected"
				changed = true
			}
		}
		if !changed {
			continue
		}
		d["_revision"] = revision(d) + 1
		if _, err = tx.Exec(ctx, "UPDATE product_documents SET data=$3,updated_at=clock_timestamp() WHERE company_id=$1 AND id::text=$2", cid, id, string(JSON(d))); err != nil {
			return dbError(err)
		}
	}
	// Linked bank orders may retain the same receipt for provenance after its
	// reservation moved to an invoice. Clear these remaining references too.
	_, err = tx.Exec(ctx, `UPDATE planned_events e SET matched_operation_id=NULL,
	 status=CASE WHEN status='received' THEN 'expected' ELSE status END,
	 extra=e.extra||jsonb_build_object('_revision',COALESCE((e.extra->>'_revision')::int,0)+1)
	 FROM operations o WHERE e.company_id=$1 AND o.company_id=e.company_id
	 AND o.source_id=$2 AND e.matched_operation_id=o.id`, cid, sourceID)
	if err != nil {
		return dbError(err)
	}
	return nil
}
