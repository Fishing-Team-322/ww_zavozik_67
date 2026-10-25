package httpapi_test

import (
	"testing"
)

func TestOperationFiltersRejectUnknownEnumValues(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	for _, filter := range []string{"direction=sideways", "category=missing", "source=xlsx"} {
		r := h.call("GET", "/v1/companies/"+cid+"/operations?"+filter, "", token)
		if r.Code != 400 {
			t.Errorf("unknown filter %s silently became an empty successful response: %d", filter, r.Code)
		}
	}
}

func TestOperationSourceFilterMatchesItsPublicDefault(t *testing.T) {
	h, _, token, cid := auditSetup(t)
	base := "/v1/companies/" + cid + "/operations?limit=1000"
	all := auditCall(t, h, token, "GET", base, nil, 200)["items"].([]any)
	if len(all) == 0 {
		t.Fatal("fixture operations missing")
	}
	for _, raw := range all {
		if raw.(map[string]any)["source"] != "upload" {
			t.Fatal("fixture public source changed", raw)
		}
	}
	filtered := auditCall(t, h, token, "GET", base+"&source=upload", nil, 200)["items"].([]any)
	if len(filtered) != len(all) {
		t.Fatalf("source filter hides rows advertised with that source: got %d want %d", len(filtered), len(all))
	}
}
