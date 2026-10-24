package product

import (
	"os"
	"path/filepath"
	"testing"
)

func TestQualityCohortsDoNotDuplicateModels(t *testing.T) {
	dir := t.TempDir()
	data := "model,companies,wape_7,gap_brier\nauto,all,0.2,0.1\nauto,unseen,0.3,0.2\n"
	if e := os.WriteFile(filepath.Join(dir, "final_audit.summary.csv"), []byte(data), 0600); e != nil {
		t.Fatal(e)
	}
	models := (&Service{ReportsDir: dir}).ModelQuality()
	if len(models) != 1 || models[0]["wape_7"] != 0.2 || models[0]["gap_brier"] != 0.1 {
		t.Fatal(models)
	}
}
