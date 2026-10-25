package product

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"testing"
)

func TestDiscoveryAssignmentSurvivesOperationDocumentProjection(t *testing.T) {
	op := domain.Operation{Discovery: &domain.DiscoveredAssignment{Status: "coarse_only", CoarseCategoryID: "open-group", CategoryPath: []string{"open-group"}, TaxonomyVersion: "v1", ForecastCategory: domain.CatOther}}
	extra := operationImportExtra(op, "upload")
	decoded := Doc(store.Decode(store.JSON(extra)))
	displayed := view("operation", decoded)
	got, ok := displayed["discovery"].(map[string]any)
	if !ok || got["coarse_category_id"] != "open-group" || got["status"] != "coarse_only" {
		t.Fatalf("native category disappeared: %+v", displayed)
	}
}
func TestProductionDefaultIsResolvedBeforeForecastCacheKey(t *testing.T) {
	t.Setenv("FORECAST_DEFAULT_MODEL", "structural_m6")
	if defaultServingModel() != "structural_m6" {
		t.Fatal("default model must not retain an old auto cache key")
	}
}
