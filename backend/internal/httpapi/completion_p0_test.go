package httpapi_test

import (
	"context"
	"fmt"
	"strings"
	"testing"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/google/uuid"
)

func TestCompletionSelfServiceAndOptionalFilters(t *testing.T) {
	h := integration(t)
	owner, _ := h.register("self-service@example.invalid")
	other, _ := h.register("separate-owner@example.invalid")
	body := `{"name":"Self service","legal_form":"ООО","industry":"tests","inn":"6164138513"}`
	created := h.call("POST", "/v1/companies", body, owner)
	status(t, created, 201)
	c := decode[platform.Company](t, created)
	base := "/v1/companies/" + c.ID
	// The same registry INN creates an independent workspace, never a membership in the first one.
	second := h.call("POST", "/v1/companies", body, other)
	status(t, second, 201)
	if decode[platform.Company](t, second).ID == c.ID {
		t.Fatal("INN granted an existing tenant")
	}
	status(t, h.call("GET", base, "", other), 404)
	status(t, h.call("POST", "/v1/companies", strings.ReplaceAll(body, "6164138513", "6164138512"), owner), 400)
	for _, query := range []string{"", "?counterparty_id=", "?counterparty_id=" + uuid.NewString()} {
		r := h.call("GET", base+"/operations"+query, "", owner)
		status(t, r, 200)
	}
	r := h.call("GET", base+"/operations?counterparty_id=invalid", "", owner)
	status(t, r, 400)
	if strings.Contains(r.Body.String(), "unmarshaling") {
		t.Fatal("raw UUID error leaked")
	}
	ctx := context.Background()
	for i, read := range []bool{false, true} {
		_, err := h.db.ProductSave(ctx, decode[product.Doc](t, h.call("GET", "/v1/me", "", owner))["id"].(string), c.ID, "alert", uuid.NewString(), product.Doc{"title": fmt.Sprint(i), "body": "Fixture", "severity": "info", "kind": "gap_risk", "read": read, "ref": product.Doc{"screen": "dashboard", "id": nil}}, true)
		if err != nil {
			t.Fatal(err)
		}
	}
	for _, tc := range []struct {
		query string
		count int
	}{{"", 2}, {"?unread=", 2}, {"?unread=true", 1}, {"?unread=false", 1}} {
		r := h.call("GET", base+"/alerts"+tc.query, "", owner)
		status(t, r, 200)
		if n := len(decode[struct {
			Items []product.Doc `json:"items"`
		}](t, r).Items); n != tc.count {
			t.Fatalf("%s: got %d, want %d", tc.query, n, tc.count)
		}
	}
	r = h.call("GET", base+"/alerts?unread=invalid", "", owner)
	status(t, r, 400)
	if strings.Contains(r.Body.String(), "strconv") {
		t.Fatal("raw bool error leaked")
	}
}

func TestCompletionUnknownZeroAndMeasuredBalances(t *testing.T) {
	h := integration(t)
	owner, _ := h.register("balance-source@example.invalid")
	for _, tc := range []struct {
		name    string
		balance any
	}{{"unknown", nil}, {"zero", 0.0}, {"measured", 123456.78}} {
		r := h.call("POST", "/v1/companies", `{"name":"`+tc.name+`","legal_form":"ООО","industry":"tests"}`, owner)
		status(t, r, 201)
		cid := decode[platform.Company](t, r).ID
		_, err := h.db.Pool.Exec(context.Background(), `INSERT INTO operations(id,company_id,op_date,amount,direction,counterparty_name,purpose,balance_eod,category,category_method,dedup_hash,extra) VALUES($1,$2,$3,100,'in','Fixture','Balance regression',$4,'other','rule',$1,'{}')`, uuid.NewString(), cid, time.Now().UTC().Format("2006-01-02"), tc.balance)
		if err != nil {
			t.Fatal(err)
		}
		r = h.call("GET", "/v1/companies/"+cid+"/dashboard", "", owner)
		status(t, r, 200)
		d := decode[product.Doc](t, r)
		if tc.balance == nil {
			if d["balance_now"] != nil || d["forecast"] != nil {
				t.Fatal("unknown balance invented", d)
			}
		} else if d["balance_now"] != tc.balance {
			t.Fatalf("%s: got balance %v want %v", tc.name, d["balance_now"], tc.balance)
		}
	}
}
