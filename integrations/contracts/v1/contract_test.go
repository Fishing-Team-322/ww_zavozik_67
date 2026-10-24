package v1

import (
	"encoding/json"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"os"
	"testing"
)

func TestExampleMatchesGoContract(t *testing.T) {
	schemaBytes, err := os.ReadFile("import-batch.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	var schema map[string]any
	if err = json.Unmarshal(schemaBytes, &schema); err != nil {
		t.Fatal(err)
	}
	bytes, err := os.ReadFile("example-import-batch.json")
	if err != nil {
		t.Fatal(err)
	}
	var batch contracts.ImportBatch
	if err = json.Unmarshal(bytes, &batch); err != nil {
		t.Fatal(err)
	}
	if batch.SchemaVersion != contracts.SchemaVersion || batch.CompanyID != "demo-company" || len(batch.Operations) != 1 || len(batch.PlannedEvents) != 1 {
		t.Fatalf("example: %+v", batch)
	}
	if batch.Operations[0].AmountKopecks+batch.PlannedEvents[0].RemainingKopecks != batch.PlannedEvents[0].TotalKopecks {
		t.Fatal("paid plus remaining mismatch")
	}
	var fields map[string]any
	if err = json.Unmarshal(bytes, &fields); err != nil {
		t.Fatal(err)
	}
	for _, raw := range schema["required"].([]any) {
		if _, ok := fields[raw.(string)]; !ok {
			t.Fatalf("missing required field %s", raw)
		}
	}
	if _, err = json.Marshal(batch); err != nil {
		t.Fatal(err)
	}
}
