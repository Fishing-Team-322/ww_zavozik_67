package httpapi_test

import (
	"context"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/migrations"
)

func TestDocumentDefaultMigrationPreservesOptOutAndPaidHistory(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid
	ctx := context.Background()
	create := func(number string, additional bool) product.Doc {
		return auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": number, "direction": "received", "amount": 1000, "issued_at": "2026-10-23", "due_at": "2026-10-26", "additional": additional}, 201)
	}
	legacy, covered, paid := create("Legacy missing flag", true), create("Explicit baseline", false), create("Paid document", true)
	auditCall(t, h, token, "PATCH", "/v1/invoices/"+paid["id"].(string), product.Doc{"status": "paid"}, 200)
	for _, doc := range []product.Doc{legacy, paid} {
		if _, e := h.db.Pool.Exec(ctx, "UPDATE product_documents SET data=data-'additional' WHERE id=$1", doc["id"]); e != nil {
			t.Fatal(e)
		}
		if _, e := h.db.Pool.Exec(ctx, "UPDATE planned_events SET extra=extra-'additional' WHERE company_id=$1 AND extra->>'document_id'=$2", cid, doc["id"]); e != nil {
			t.Fatal(e)
		}
	}
	raw, e := migrations.Files.ReadFile("00010_document_forecast_defaults.sql")
	if e != nil {
		t.Fatal(e)
	}
	up := strings.Split(string(raw), "-- +goose Down")[0]
	if _, e = h.db.Pool.Exec(ctx, up); e != nil {
		t.Fatal(e)
	}
	for _, tc := range []struct {
		doc        product.Doc
		additional bool
		status     string
	}{{legacy, true, "expected"}, {covered, false, "expected"}, {paid, true, "received"}} {
		var additional bool
		var state string
		if e = h.db.Pool.QueryRow(ctx, "SELECT (extra->>'additional')::bool,status FROM planned_events WHERE company_id=$1 AND extra->>'document_id'=$2", cid, tc.doc["id"]).Scan(&additional, &state); e != nil {
			t.Fatal(e)
		}
		if additional != tc.additional || state != tc.status {
			t.Fatal("migration changed explicit opt-out or paid history", additional, state)
		}
	}
	var before, after int64
	h.db.Pool.QueryRow(ctx, "SELECT data_revision FROM companies WHERE id=$1", cid).Scan(&before)
	if _, e = h.db.Pool.Exec(ctx, up); e != nil {
		t.Fatal(e)
	}
	h.db.Pool.QueryRow(ctx, "SELECT data_revision FROM companies WHERE id=$1", cid).Scan(&after)
	if before != after {
		t.Fatal("migration not idempotent", before, after)
	}
}
