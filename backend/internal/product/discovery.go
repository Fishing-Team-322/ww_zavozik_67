package product

import (
	"context"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"os"
)

func operationImportExtra(op domain.Operation, source string) Doc {
	extra := Doc{"source": source}
	if op.Discovery != nil {
		extra["discovery"] = op.Discovery
	}
	return extra
}

func (s *Service) discoveredCategories(ctx context.Context) (Result, error) {
	model, ok := s.Categorizer.(*categorize.Discovery)
	if !ok {
		return Result{}, platform.Fail(503, "discovery_not_configured", "Модель экономических групп не подключена")
	}
	taxonomy, err := model.Taxonomy(ctx)
	if err != nil {
		return Result{}, platform.Fail(503, "discovery_unavailable", "Модель экономических групп недоступна")
	}
	out := []Doc{}
	for _, n := range taxonomy.GetCategories() {
		out = append(out, Doc{"id": n.GetId(), "title": n.GetTitle(), "parent_id": n.GetParentId(), "node_kind": n.GetNodeKind(), "direction": n.GetDirection(), "independent_families": n.GetIndependentFamilies(), "companies": n.GetCompanies(), "title_status": n.GetTitleStatus(), "taxonomy_version": taxonomy.GetTaxonomyVersion(), "encoder_version": taxonomy.GetEncoderVersion(), "status": "research_weak_supervision", "embedding_dimension": 1024})
	}
	return okResult(out), nil
}
func okResult(body any) Result { return Result{Status: 200, Body: body} }

// Resolve auto before the incremental-cache key, so a model deployment cannot
// reuse paths from the preceding serving model under the same "auto" key.
func defaultServingModel() string {
	if name := os.Getenv("FORECAST_DEFAULT_MODEL"); name != "" {
		return name
	}
	return "auto"
}

func (s *Service) discoveryQuality(ctx context.Context) (Result, error) {
	model := s.Categorizer.(*categorize.Discovery)
	taxonomy, err := model.Taxonomy(ctx)
	if err != nil {
		return Result{}, platform.Fail(503, "discovery_unavailable", "Модель экономических групп недоступна")
	}
	var corrections int
	if err = s.DB.Pool.QueryRow(ctx, "SELECT count(*) FROM category_corrections WHERE created_at>now()-interval '7 days'").Scan(&corrections); err != nil {
		return Result{}, err
	}
	return ok(Doc{"accuracy": nil, "macro_f1": nil, "by_category": []Doc{}, "user_corrections_week": corrections, "retrained_at": nil, "source": "live_qwen_discovery", "taxonomy_version": taxonomy.GetTaxonomyVersion(), "status": "research_weak_supervision", "limitations": []string{"no_independent_human_accuracy", "weak_pair_metrics_are_not_operation_accuracy", "native_categories_may_abstain"}})
}
