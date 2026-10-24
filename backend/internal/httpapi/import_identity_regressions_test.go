package httpapi_test

import (
	"bytes"
	"context"
	"mime/multipart"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/migrations"
	"github.com/xuri/excelize/v2"
)

func importAuditCSV(t *testing.T, h *harness, s *product.Service, token, cid, body string) product.Doc {
	t.Helper()
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	p, e := w.CreateFormFile("file", "synthetic.csv")
	if e != nil {
		t.Fatal(e)
	}
	_, _ = p.Write([]byte(body))
	_ = w.Close()
	r := httptest.NewRequest("POST", "/v1/companies/"+cid+"/uploads", &buf)
	r.Header.Set("Authorization", "Bearer "+token)
	r.Header.Set("Content-Type", w.FormDataContentType())
	out := httptest.NewRecorder()
	h.handler.ServeHTTP(out, r)
	status(t, out, 202)
	job := decode[product.Doc](t, out)
	drainCase(t, s)
	done := auditCall(t, h, token, "GET", "/v1/jobs/"+job["id"].(string), nil, 200)
	if done["status"] != "done" {
		t.Fatal(done)
	}
	return auditCall(t, h, token, "GET", done["result_ref"].(string), nil, 200)
}
func TestImportReportsReusedIDWithDifferentAmount(t *testing.T) {
	for _, changed := range []string{"200", "100.01"} {
		t.Run(changed, func(t *testing.T) {
			h, s, token, cid := auditSetup(t)
			head := "date;amount;direction;counterparty;purpose;balance;id\n"
			importAuditCSV(t, h, s, token, cid, head+"2026-10-24;100;in;CSV client;Services;109100;stable-id\n")
			got := importAuditCSV(t, h, s, token, cid, head+"2026-10-24;"+changed+";in;CSV client;Services;109100;stable-id\n")
			if len(got["errors"].([]any)) == 0 || got["duplicates"] != float64(0) {
				t.Fatalf("changed bank fact was silently labelled a duplicate: %v", got)
			}
			var amount float64
			e := h.db.Pool.QueryRow(context.Background(), "SELECT amount::float8 FROM operations WHERE company_id=$1 AND counterparty_name='CSV client'", cid).Scan(&amount)
			if e != nil {
				t.Fatal(e)
			}
			if amount != 100 {
				t.Fatalf("conflicting import rewrote historical amount: %.2f", amount)
			}
		})
	}
}

func TestRejectedRowsDoNotShiftAnonymousPaymentIdentity(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	head := "date;amount;direction;counterparty;purpose;balance\n"
	valid := "2026-10-24;100;in;Anonymous client;Services;109100\n"
	importAuditCSV(t, h, s, token, cid, head+valid)
	report := importAuditCSV(t, h, s, token, cid, head+"2026-10-24;100;in;Anonymous client;Services;invalid\n"+valid)
	if report["added"] != float64(0) || report["duplicates"] != float64(1) || len(report["errors"].([]any)) != 1 {
		t.Fatal("a rejected balance row shifted the valid payment's identity", report)
	}
}

func TestExcelImportUsesPublicSourceKindAndRepairsLegacyRecords(t *testing.T) {
	h, s, token, cid := auditSetup(t)
	book := excelize.NewFile()
	defer book.Close()
	for i, row := range [][]any{{"date", "amount", "direction", "counterparty", "balance", "id"}, {"2026-10-24", 100, "in", "Excel audit", 109100, "excel-one"}} {
		cell, _ := excelize.CoordinatesToCellName(1, i+1)
		if err := book.SetSheetRow("Sheet1", cell, &row); err != nil {
			t.Fatal(err)
		}
	}
	buf, err := book.WriteToBuffer()
	if err != nil {
		t.Fatal(err)
	}
	report := importAuditCSV(t, h, s, token, cid, string(buf.Bytes()))
	if report["source"].(map[string]any)["kind"] != "excel" {
		t.Fatal("internal XLSX format leaked into the public source enum", report)
	}
	base := "/v1/companies/" + cid
	status(t, h.call("GET", base+"/sources", "", token), 200)
	status(t, h.call("GET", base+"/operations", "", token), 200)
	// Recreate the old persisted representation and apply the actual upgrade.
	ctx := context.Background()
	if _, err = h.db.Pool.Exec(ctx, "UPDATE sources SET kind='xlsx' WHERE id=$1", report["source_id"]); err != nil {
		t.Fatal(err)
	}
	if _, err = h.db.Pool.Exec(ctx, `UPDATE operations SET extra=extra||'{"source":"xlsx"}'::jsonb WHERE source_id=$1`, report["source_id"]); err != nil {
		t.Fatal(err)
	}
	if _, err = h.db.Pool.Exec(ctx, `UPDATE product_documents SET data=jsonb_set(data,'{source,kind}','"xlsx"'::jsonb) WHERE id=$1`, report["id"]); err != nil {
		t.Fatal(err)
	}
	raw, err := migrations.Files.ReadFile("00009_excel_source_kind.sql")
	if err != nil {
		t.Fatal(err)
	}
	if _, err = h.db.Pool.Exec(ctx, strings.SplitN(string(raw), "-- +goose Down", 2)[0]); err != nil {
		t.Fatal(err)
	}
	status(t, h.call("GET", base+"/sources", "", token), 200)
	status(t, h.call("GET", base+"/operations", "", token), 200)
	repaired := auditCall(t, h, token, "GET", "/v1/imports/"+report["id"].(string), nil, 200)
	if repaired["source"].(map[string]any)["kind"] != "excel" {
		t.Fatal("legacy import report was not repaired", repaired)
	}
}
func TestRepeatImportCanFillAnUnknownClosingBalance(t *testing.T) {
	for _, raw := range []string{"109100", "0"} {
		t.Run(raw, func(t *testing.T) {
			h, s, token, cid := auditSetup(t)
			head := "date;amount;direction;counterparty;purpose;balance;id\n"
			importAuditCSV(t, h, s, token, cid, head+"2026-10-24;100;in;CSV client;Services;;stable-id\n")
			importAuditCSV(t, h, s, token, cid, head+"2026-10-24;100;in;CSV client;Services;"+raw+";stable-id\n")
			var balance *float64
			e := h.db.Pool.QueryRow(context.Background(), "SELECT balance_eod::float8 FROM operations WHERE company_id=$1 AND counterparty_name='CSV client'", cid).Scan(&balance)
			if e != nil {
				t.Fatal(e)
			}
			want := float64(109100)
			if raw == "0" {
				want = 0
			}
			if balance == nil || *balance != want {
				t.Fatalf("known closing balance was discarded on repeat import: %v", balance)
			}
		})
	}
}
