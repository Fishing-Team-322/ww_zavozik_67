package categorize

import (
	"context"
	categorizev1 "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/categorize/v1"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"testing"
)

func TestHybridCorrectsRuleButPreservesManualLabel(t *testing.T) {
	purpose := "Перечисление остатка в связи с закрытием счета"
	fake := &fakeML{answers: map[string]*categorizev1.Classification{purpose: {Category: "own_transfer", Confidence: .99}}}
	h := Hybrid{ML: &MLCategorizer{Client: fake}}
	ops := outOps(purpose, purpose)
	ops[1].Category = domain.CatSupplier
	ops[1].CategoryMethod = domain.MethodUser
	got, err := h.Categorize(context.Background(), ops)
	if err != nil {
		t.Fatal(err)
	}
	if got[0].Category != domain.CatOwnTransfer || got[1].Category != domain.CatSupplier || got[1].Method != domain.MethodUser {
		t.Fatalf("%+v", got)
	}
	if len(fake.batches) != 1 || fake.batches[0] != 1 {
		t.Fatalf("manual label sent to model: %v", fake.batches)
	}
}
