package httpapi_test

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/google/uuid"
)

func TestDeletingSourceRevertsOnlyItsBankSettlements(t *testing.T) {
	for _, name := range []string{"remove_facts", "keep_facts", "legacy_matches"} {
		keep := name == "keep_facts"
		t.Run(name, func(t *testing.T) {
			h, s, token, cid := auditSetup(t)
			base := "/v1/companies/" + cid
			invoice := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "Partial invoice", "direction": "issued", "amount": 10000, "paid_amount": 4000, "issued_at": "2026-10-20", "due_at": "2026-10-24", "counterparty_name": "Invoice client"}, 201)
			contract := auditCall(t, h, token, "POST", base+"/contracts", product.Doc{"number": "Contract", "direction": "in", "total": 7000, "counterparty_name": "Contract client", "schedule": []product.Doc{{"date": "2026-10-24", "amount": 7000, "status": "expected"}}}, 201)
			auditCall(t, h, token, "POST", base+"/events", product.Doc{"title": "Manual", "date": "2026-10-24", "amount": 8000, "direction": "in", "counterparty_name": "Manual client"}, 201)
			auditCall(t, h, token, "POST", base+"/taxes", product.Doc{"request_id": uuid.NewString(), "kind": "other", "period": "audit", "year": 2026, "due_date": "2026-10-24", "amount": 9000, "title": "Tax", "source_ref": "Synthetic audit", "confirmed": true, "additional": true}, 201)
			csv := "date;amount;direction;counterparty;purpose;balance;id\n2026-10-24;6000;in;Invoice client;Services;121000;inv\n2026-10-24;7000;in;Contract client;Services;121000;contract\n2026-10-24;8000;in;Manual client;Services;121000;manual\n2026-10-24;9000;out;ФНС;Уплата налога НДС;121000;tax\n"
			report := importAuditCSV(t, h, s, token, cid, csv)
			ctx := context.Background()
			var received int
			if err := h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM planned_events WHERE company_id=$1 AND status='received'", cid).Scan(&received); err != nil {
				t.Fatal(err)
			}
			if received != 4 {
				t.Fatal("fixture bank payments not reconciled", received)
			}
			// Rebuilding a paid invoice's projection replaces its residual amount
			// with the full amount; undo must use the actual bank contribution.
			auditCall(t, h, token, "PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"number": "Renamed paid invoice"}, 200)
			if name == "legacy_matches" {
				if _, err := h.db.Pool.Exec(ctx, "DELETE FROM operation_settlements WHERE company_id=$1", cid); err != nil {
					t.Fatal(err)
				}
			}
			auditCall(t, h, token, "DELETE", "/v1/sources/"+report["source_id"].(string), product.Doc{"keep_data": keep}, 204)
			var paid float64
			if err := h.db.Pool.QueryRow(ctx, "SELECT (data->>'paid_amount')::float8 FROM product_documents WHERE id=$1", invoice["id"]).Scan(&paid); err != nil {
				t.Fatal(err)
			}
			want := float64(4000)
			if keep {
				want = 10000
			}
			if paid != want {
				t.Errorf("deleted bank contribution was retained or manual payment lost: got %v want %v", paid, want)
			}
			var state string
			if err := h.db.Pool.QueryRow(ctx, "SELECT data->'schedule'->0->>'status' FROM product_documents WHERE id=$1", contract["id"]).Scan(&state); err != nil {
				t.Fatal(err)
			}
			wantState := "expected"
			if keep {
				wantState = "received"
			}
			if state != wantState {
				t.Errorf("contract retained a deleted receipt: %s", state)
			}
			if err := h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM planned_events WHERE company_id=$1 AND (status='received' OR matched_operation_id IS NOT NULL)", cid).Scan(&received); err != nil {
				t.Fatal(err)
			}
			wantReceived := 0
			if keep {
				wantReceived = 4
			}
			if received != wantReceived {
				t.Errorf("stale event payment references after source removal: %d", received)
			}
			if !keep {
				// The same bank facts can be loaded and reconciled again.
				importAuditCSV(t, h, s, token, cid, csv)
				if err := h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM planned_events WHERE company_id=$1 AND status='received'", cid).Scan(&received); err != nil {
					t.Fatal(err)
				}
				if received != 4 {
					t.Fatal("stale bank references prevented reimport settlement", received)
				}
			}
		})
	}
}

func TestInFlightSheetSyncCannotRestoreRemovedOrDisabledSource(t *testing.T) {
	for _, action := range []string{"delete", "disable"} {
		t.Run(action, func(t *testing.T) {
			h, s, token, cid := auditSetup(t)
			s.EncryptionKey = bytes.Repeat([]byte("s"), 32)
			started, release := make(chan struct{}), make(chan struct{})
			s.HTTP = &http.Client{Transport: sourceFixtureTransport(func(r *http.Request) (*http.Response, error) {
				close(started)
				select {
				case <-release:
				case <-r.Context().Done():
					return nil, r.Context().Err()
				}
				return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(`{"values":[["date","amount","direction","counterparty","balance","id"],["2026-10-24","100","in","In-flight client","109100","sheet-one"]]}`))}, nil
			})}
			source := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/sources", product.Doc{"kind": "gsheets", "title": "Synthetic sheet", "config": product.Doc{"spreadsheet_id": "synthetic-sheet"}}, 201)
			drainCase(t, s)
			job := auditCall(t, h, token, "POST", "/v1/sources/"+source["id"].(string)+"/sync", nil, 202)
			ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
			defer cancel()
			done := make(chan error, 1)
			finished := false
			go func() { _, err := s.ProcessOne(ctx); done <- err }()
			defer func() {
				cancel()
				if finished {
					return
				}
				select {
				case <-done:
				case <-time.After(2 * time.Second):
				}
			}()
			select {
			case <-started:
			case <-ctx.Done():
				t.Fatal("sheet sync did not start")
			}
			if action == "delete" {
				auditCall(t, h, token, "DELETE", "/v1/sources/"+source["id"].(string), product.Doc{"keep_data": false}, 204)
			} else {
				auditCall(t, h, token, "PATCH", "/v1/sources/"+source["id"].(string), product.Doc{"enabled": false}, 200)
			}
			close(release)
			select {
			case err := <-done:
				finished = true
				if err != nil {
					t.Fatal(err)
				}
			case <-ctx.Done():
				t.Fatal("sheet sync did not finish")
			}
			result := auditCall(t, h, token, "GET", "/v1/jobs/"+job["id"].(string), nil, 200)
			if result["status"] != "failed" {
				t.Error("obsolete sync was accepted", result)
			}
			var count int
			if err := h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM operations WHERE company_id=$1 AND counterparty_name='In-flight client'", cid).Scan(&count); err != nil {
				t.Fatal(err)
			}
			if count != 0 {
				t.Error("an obsolete source committed bank operations", count)
			}
			if action == "delete" {
				if err := h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM sources WHERE id=$1", source["id"]).Scan(&count); err != nil {
					t.Fatal(err)
				}
				if count != 0 {
					t.Error("sync resurrected the deleted source")
				}
			}
		})
	}
}

func TestRemovingOneSourcePreservesPaymentsFromAnother(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	invoice := auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "Multiple receipts", "direction": "issued", "amount": 14000, "paid_amount": 4000, "issued_at": "2026-10-20", "due_at": "2026-10-24", "counterparty_name": "Multiple client"}, 201)
	report := importAuditCSV(t, h, s, token, cid, "date;amount;direction;counterparty;purpose;balance;id\n2026-10-24;10000;in;Multiple client;Services;119000;first-receipt\n")
	auditCall(t, h, token, "PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"amount": 24000}, 200)
	otherSource := auditCall(t, h, token, "POST", base+"/sources", product.Doc{"kind": "manual", "title": "Second bank source"}, 201)
	second := auditOperation(t, h, cid, "2026-10-24", "Multiple client", "", 10000, 129000)
	ctx := context.Background()
	if _, err := h.db.Pool.Exec(ctx, "UPDATE operations SET source_id=$3 WHERE company_id=$1 AND id=$2", cid, second, otherSource["id"]); err != nil {
		t.Fatal(err)
	}
	if _, err := h.db.Pool.Exec(ctx, "UPDATE operations SET balance_eod=129000 WHERE company_id=$1 AND op_date='2026-10-24'", cid); err != nil {
		t.Fatal(err)
	}
	drainCase(t, s)
	paid := auditCall(t, h, token, "PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"number": "Both receipts recorded"}, 200)
	if paid["paid_amount"] != float64(24000) {
		t.Fatal("fixture second receipt was not reconciled", paid)
	}
	auditCall(t, h, token, "DELETE", "/v1/sources/"+report["source_id"].(string), product.Doc{"keep_data": false}, 204)
	paid = auditCall(t, h, token, "PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"number": "First receipt removed"}, 200)
	if paid["paid_amount"] != float64(14000) || paid["status"] != "partial" {
		t.Fatal("payment from the other source or manual payment lost", paid)
	}
	var operation string
	if err := h.db.Pool.QueryRow(ctx, "SELECT matched_operation_id FROM planned_events WHERE company_id=$1 AND extra->>'document_id'=$2", cid, invoice["id"]).Scan(&operation); err != nil {
		t.Fatal(err)
	}
	if operation != second {
		t.Fatal("remaining bank reference was lost", operation)
	}
	auditCall(t, h, token, "DELETE", "/v1/sources/"+otherSource["id"].(string), product.Doc{"keep_data": false}, 204)
	paid = auditCall(t, h, token, "PATCH", "/v1/invoices/"+invoice["id"].(string), product.Doc{"number": "Both bank sources removed"}, 200)
	if paid["paid_amount"] != float64(4000) || paid["paid_at"] != nil {
		t.Fatal("manual amount lost or removed bank date retained", paid)
	}
}

func TestRemovingTaxReceiptDoesNotReviveCancelledLiability(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	tax := auditCall(t, h, token, "POST", "/v1/companies/"+cid+"/taxes", product.Doc{"request_id": uuid.NewString(), "kind": "other", "period": "audit", "year": 2026, "due_date": "2026-10-24", "amount": 9000, "title": "Tax", "source_ref": "Synthetic audit", "confirmed": true, "additional": true}, 201)
	report := importAuditCSV(t, h, s, token, cid, "date;amount;direction;counterparty;purpose;balance;id\n2026-10-24;9000;out;ФНС;Уплата налога НДС;100000;cancelled-tax\n")
	ctx := context.Background()
	var state string
	if err := h.db.Pool.QueryRow(ctx, "SELECT status FROM planned_events WHERE company_id=$1 AND extra->>'tax_id'=$2", cid, tax["id"]).Scan(&state); err != nil {
		t.Fatal(err)
	}
	if state != "received" {
		t.Fatal("fixture tax not settled", state)
	}
	auditCall(t, h, token, "POST", "/v1/taxes/"+tax["id"].(string)+"/cancel", nil, 204)
	auditCall(t, h, token, "DELETE", "/v1/sources/"+report["source_id"].(string), product.Doc{"keep_data": false}, 204)
	if err := h.db.Pool.QueryRow(ctx, "SELECT status FROM planned_events WHERE company_id=$1 AND extra->>'tax_id'=$2", cid, tax["id"]).Scan(&state); err != nil {
		t.Fatal(err)
	}
	if state != "cancelled" {
		t.Fatal("removing a bank receipt revived a cancelled tax", state)
	}
}
