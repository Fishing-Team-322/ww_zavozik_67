package httpapi_test

import (
	"bytes"
	"context"
	"mime/multipart"
	"net/http/httptest"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
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
	h, s, token, cid := auditSetup(t)
	head := "date;amount;direction;counterparty;purpose;balance;id\n"
	importAuditCSV(t, h, s, token, cid, head+"2026-10-24;100;in;CSV client;Services;109100;stable-id\n")
	got := importAuditCSV(t, h, s, token, cid, head+"2026-10-24;200;in;CSV client;Services;109200;stable-id\n")
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
