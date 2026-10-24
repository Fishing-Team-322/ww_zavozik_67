package httpapi_test

import (
	"context"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestCounterpartyMonthlyTotalsUseBusinessFacts(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	ctx := context.Background()
	auditOperation(t, h, cid, "2026-10-24", "Monthly client", "", 1000, 112000)
	duplicate := auditOperation(t, h, cid, "2026-10-24", "Monthly client", "", 1000, 112000)
	internal := auditOperation(t, h, cid, "2026-10-24", "Monthly client", "", 1000, 112000)
	if _, err := h.db.Pool.Exec(ctx, "UPDATE operations SET is_duplicate=(id=$2),is_internal=(id=$3) WHERE company_id=$1 AND id IN ($2,$3)", cid, duplicate, internal); err != nil {
		t.Fatal(err)
	}
	r := h.call("GET", "/v1/companies/"+cid+"/counterparties?q=Monthly%20client", "", token)
	status(t, r, 200)
	rows := decode[[]product.Doc](t, r)
	if len(rows) != 1 {
		t.Fatal(rows)
	}
	detail := auditCall(t, h, token, "GET", "/v1/companies/"+cid+"/counterparties/"+rows[0]["id"].(string), nil, 200)
	months := detail["monthly"].([]any)
	if len(months) != 1 || months[0].(map[string]any)["in"] != float64(1000) || detail["turnover_in_12m"] != float64(1000) {
		t.Fatal("monthly cash includes duplicate or internal movements", detail)
	}
}

func TestInvoiceOnlyCounterpartiesAppearUnderTheirBusinessRoles(t *testing.T) {
	for _, direction := range []string{"issued", "received"} {
		t.Run(direction, func(t *testing.T) {
			h, _, token, cid := auditSetup(t)
			base := "/v1/companies/" + cid
			auditCall(t, h, token, "POST", base+"/invoices", product.Doc{"number": "Unpaid relationship", "direction": direction, "amount": 1000, "issued_at": "2026-10-20", "due_at": "2026-10-28", "counterparty_name": "Invoice-only company"}, 201)
			role := "client"
			if direction == "received" {
				role = "supplier"
			}
			r := h.call("GET", base+"/counterparties?role="+role+"&q=Invoice-only", "", token)
			status(t, r, 200)
			rows := decode[[]product.Doc](t, r)
			if len(rows) != 1 {
				t.Fatal("a real invoice relationship disappeared from its role filter", role, rows)
			}
		})
	}
}
