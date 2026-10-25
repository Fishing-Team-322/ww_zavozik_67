package httpapi_test

import (
	"context"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestAdminRetryDoesNotQueueFileOrDisabledSources(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	ctx := context.Background()
	if _, err := h.db.Pool.Exec(ctx, "UPDATE users SET role='admin' WHERE id=(SELECT user_id FROM memberships WHERE company_id=$1 AND role='owner')", cid); err != nil {
		t.Fatal(err)
	}
	base := "/v1/companies/" + cid
	for _, kind := range []string{"upload", "excel", "onec_bank_file", "manual", "fns"} {
		source := auditCall(t, h, token, "POST", base+"/sources", product.Doc{"kind": kind, "title": "UI retry fixture"}, 201)
		id := source["id"].(string)
		path := "/v1/admin/integrations/" + id + "/retry"
		if kind == "fns" {
			auditCall(t, h, token, "PATCH", "/v1/sources/"+id, product.Doc{"enabled": false}, 200)
		}
		rejected := auditCall(t, h, token, "POST", path, nil, 409)
		wantCode := "source_not_syncable"
		if kind == "fns" {
			wantCode = "source_disabled"
		}
		if rejected["code"] != wantCode {
			t.Fatal(rejected)
		}
		var jobs int
		if err := h.db.Pool.QueryRow(ctx, "SELECT count(*) FROM product_jobs WHERE company_id=$1 AND kind='sync' AND payload->>'source_id'=$2", cid, id).Scan(&jobs); err != nil || jobs != 0 {
			t.Fatal("rejected action queued work", jobs, err)
		}
		if kind == "fns" {
			auditCall(t, h, token, "PATCH", "/v1/sources/"+id, product.Doc{"enabled": true}, 200)
			auditCall(t, h, token, "POST", path, nil, 202)
		}
	}
}
