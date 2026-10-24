package httpapi_test

import (
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func TestScenarioMovingDistantReceiptPreservesRiskQuantiles(t *testing.T) {
	for _, direction := range []string{"in", "out"} {
		for _, probability := range []float64{0, 0.5, 1} {
			h, _, token, cid := auditSetup(t)
			base := "/v1/companies/" + cid
			event := auditCall(t, h, token, "POST", base+"/events", product.Doc{"date": "2026-12-01", "title": "Uncertain distant payment", "direction": direction, "amount": 10000, "additional": true, "probability": probability}, 201)
			comparison := auditCall(t, h, token, "POST", base+"/scenarios/preview", product.Doc{"steps": []product.Doc{{"kind": "move_event", "event_id": event["id"], "date": "2026-10-26"}}}, 200)
			points := comparison["scenario"].(map[string]any)["points"].([]any)
			point := points[2].(map[string]any)
			low, high := float64(109000), float64(119000)
			paid := high
			if direction == "out" {
				low, high, paid = 99000, 109000, 99000
			}
			if probability == 0 {
				low, high = 109000, 109000
			}
			if probability == 1 {
				low, high = paid, paid
			}
			if point["p10"] != low || point["p90"] != high {
				t.Fatalf("moving %s probability %v changed the API risk bounds: %v", direction, probability, point)
			}
		}
	}
}
