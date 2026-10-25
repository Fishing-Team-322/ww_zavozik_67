package categorize

import (
	"context"
	discovery "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/categorize/v3"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"google.golang.org/grpc"
	"math"
	"testing"
)

type nativeClient struct {
	discovery.DiscoveryServiceClient
	response *discovery.AssignResponse
}

func (c nativeClient) Assign(context.Context, *discovery.AssignRequest, ...grpc.CallOption) (*discovery.AssignResponse, error) {
	return c.response, nil
}

type emptyRules struct{}

func (emptyRules) Categorize(_ context.Context, ops []domain.Operation) ([]Result, error) {
	return make([]Result, len(ops)), nil
}
func nativeResponse(id string) *discovery.AssignResponse {
	return &discovery.AssignResponse{EmbeddingDim: 1024, TaxonomyVersion: "native-v1", ScoreKind: "weakly_calibrated_relation_cosine_not_probability", Results: []*discovery.Assignment{{Id: id, Embedding: make([]float32, 1024), Status: "unknown", ForecastCategory: "other", ForecastProjectionVersion: "projection-v1"}}}
}
func TestDiscoveryKeepsAbstentionSeparateFromCompatibility(t *testing.T) {
	response := nativeResponse("a")
	model := Discovery{Client: nativeClient{response: response}, Rules: emptyRules{}}
	got, err := model.Categorize(context.Background(), []domain.Operation{{ID: "a", Direction: domain.Out}})
	if err != nil {
		t.Fatal(err)
	}
	if got[0].Category != domain.CatOther || got[0].Discovery.Status != "unknown" || got[0].Confidence != 0 {
		t.Fatalf("abstention lost: %+v", got)
	}
}
func TestDiscoveryPreservesUserAndInternalScopeWithoutInventingConfidence(t *testing.T) {
	response := nativeResponse("a")
	r := response.Results[0]
	r.Status = "assigned"
	r.CategoryId = "native-leaf"
	r.CoarseCategoryId = "native-root"
	r.CategoryPath = []string{"native-root", "native-leaf"}
	r.ForecastCategory = "salary"
	score := float32(.99)
	r.Similarity = &score
	model := Discovery{Client: nativeClient{response: response}, Rules: emptyRules{}}
	ops := []domain.Operation{{ID: "a", Direction: domain.Out, Category: domain.CatOwnTransfer, CategoryMethod: domain.MethodUser}}
	got, err := model.Categorize(context.Background(), ops)
	if err != nil {
		t.Fatal(err)
	}
	if got[0].Category != domain.CatOwnTransfer || got[0].Method != domain.MethodUser || got[0].Discovery.CategoryID != "native-leaf" {
		t.Fatalf("manual scope lost: %+v", got)
	}
	ops[0].CategoryMethod = ""
	got, err = model.Categorize(context.Background(), ops)
	if err != nil {
		t.Fatal(err)
	}
	if got[0].Confidence != 0 || got[0].Category != domain.CatSalary {
		t.Fatalf("cosine became confidence: %+v", got)
	}
	r.ForecastCategory = "owner_loan"
	got, err = model.Categorize(context.Background(), ops)
	if err != nil {
		t.Fatal(err)
	}
	if got[0].Category.IsInternal() {
		t.Fatal("group consensus changed business scope")
	}
}
func TestDiscoveryRejectsIncompatibleOrInvalidResponses(t *testing.T) {
	for _, mutate := range []func(*discovery.AssignResponse){func(r *discovery.AssignResponse) { r.EmbeddingDim = 384 }, func(r *discovery.AssignResponse) { r.Results[0].Embedding[0] = float32(math.NaN()) }, func(r *discovery.AssignResponse) { r.Results[0].Id = "wrong" }, func(r *discovery.AssignResponse) { r.Results[0].CategoryId = "leaked-on-abstention" }, func(r *discovery.AssignResponse) { r.Results[0].ForecastCategory = "invented" }} {
		response := nativeResponse("a")
		mutate(response)
		model := Discovery{Client: nativeClient{response: response}, Rules: emptyRules{}}
		if _, err := model.Categorize(context.Background(), []domain.Operation{{ID: "a", Direction: domain.Out}}); err == nil {
			t.Fatal("invalid reply accepted")
		}
	}
}
