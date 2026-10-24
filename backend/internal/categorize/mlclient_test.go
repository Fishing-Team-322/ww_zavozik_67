package categorize

import (
	"context"
	"errors"
	"math"
	"strconv"
	"strings"
	"testing"

	"google.golang.org/grpc"

	categorizev1 "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/categorize/v1"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// fakeML отвечает категорией по назначению и запоминает размеры батчей.
type fakeML struct {
	answers map[string]*categorizev1.Classification
	batches []int
	err     error
}

func (f *fakeML) Classify(_ context.Context, in *categorizev1.ClassifyRequest, _ ...grpc.CallOption) (*categorizev1.ClassifyResponse, error) {
	if f.err != nil {
		return nil, f.err
	}
	f.batches = append(f.batches, len(in.GetOperations()))
	out := &categorizev1.ClassifyResponse{ModelVersion: "test"}
	for _, op := range in.GetOperations() {
		a, ok := f.answers[op.GetPaymentPurpose()]
		if !ok {
			a = &categorizev1.Classification{Category: "other", Confidence: 0.4}
		}
		out.Results = append(out.Results, &categorizev1.Classification{Id: op.GetId(), Category: a.GetCategory(), Confidence: a.GetConfidence()})
	}
	return out, nil
}

func outOps(purposes ...string) []domain.Operation {
	out := make([]domain.Operation, len(purposes))
	for i, p := range purposes {
		out[i] = domain.Operation{ID: p, Direction: domain.Out, Purpose: domain.Purpose(p)}
	}
	return out
}

func TestChainRulesThenML(t *testing.T) {
	fake := &fakeML{answers: map[string]*categorizev1.Classification{
		"Оплата поставщику цифровыми рублями за кровельные материалы": {Category: "supplier", Confidence: 0.97},
		"Зарплата на кошелёк цифрового рубля":                         {Category: "salary", Confidence: 0.95},
		"Что-то новое": {Category: "crypto", Confidence: 0.99}, // не из списка
		"Сомнительно":  {Category: "services", Confidence: 0.2},
		// Правила уверены — модель не спрашиваем, даже если она ответила бы иначе.
		"Комиссия за ведение счета": {Category: "services", Confidence: 0.99},
	}}
	ml := &MLCategorizer{Client: fake, MinConfidence: 0.3}
	chain := Chain{Steps: []Categorizer{DefaultRules, ml}, Threshold: 0.5}
	in := outOps("Комиссия за ведение счета", "Оплата поставщику цифровыми рублями за кровельные материалы",
		"Зарплата на кошелёк цифрового рубля", "Что-то новое", "Сомнительно")
	res, err := chain.Categorize(context.Background(), in)
	if err != nil {
		t.Fatal(err)
	}
	want := []struct {
		cat    domain.Category
		method domain.CategoryMethod
	}{
		{domain.CatBankFee, domain.MethodRule},
		{domain.CatSupplier, domain.MethodML},
		{domain.CatSalary, domain.MethodML},
		{domain.CatOther, domain.MethodRule}, // неизвестная категория от ML → «не знаю» → other
		{domain.CatOther, domain.MethodRule}, // ниже MinConfidence → other
	}
	for i, w := range want {
		if res[i].Category != w.cat || res[i].Method != w.method {
			t.Errorf("%q: got %s/%s, want %s/%s", in[i].Purpose, res[i].Category, res[i].Method, w.cat, w.method)
		}
	}
	if len(fake.batches) != 1 || fake.batches[0] != 4 {
		t.Errorf("ML must get only the 4 operations rules did not take, got batches %v", fake.batches)
	}
}

func TestMLBatching(t *testing.T) {
	fake := &fakeML{}
	ml := &MLCategorizer{Client: fake, BatchSize: 2}
	res, err := ml.Categorize(context.Background(), outOps("a", "b", "c", "d", "e"))
	if err != nil {
		t.Fatal(err)
	}
	if len(res) != 5 || len(fake.batches) != 3 || fake.batches[2] != 1 {
		t.Fatalf("batches %v, results %d", fake.batches, len(res))
	}
	for _, r := range res {
		if r.Category != domain.CatOther || r.Method != domain.MethodML {
			t.Errorf("got %+v", r)
		}
	}
}

func TestMLFailOpen(t *testing.T) {
	boom := errors.New("unavailable")
	var seen error
	ml := &MLCategorizer{Client: &fakeML{err: boom}, FailOpen: true, OnError: func(err error) { seen = err }}
	res, err := Chain{Steps: []Categorizer{DefaultRules, ml}, Threshold: 0.5}.Categorize(context.Background(),
		outOps("ЕНП", "Непонятно что"))
	if err != nil {
		t.Fatal(err)
	}
	if res[0].Category != domain.CatTax || res[1].Category != domain.CatOther || !errors.Is(seen, boom) {
		t.Errorf("fail-open: %+v, onError %v", res, seen)
	}

	strict := &MLCategorizer{Client: &fakeML{err: boom}}
	if _, err := strict.Categorize(context.Background(), outOps("x")); !errors.Is(err, boom) {
		t.Errorf("strict mode must return error, got %v", err)
	}
}

func TestMLBatchingRespectsTextBudget(t *testing.T) {
	fake := &fakeML{}
	ops := make([]domain.Operation, 500)
	for i := range ops {
		ops[i] = domain.Operation{ID: strconv.Itoa(i), Direction: domain.Out, Purpose: domain.Purpose(strings.Repeat("a", 5000))}
	}
	result, err := (&MLCategorizer{Client: fake}).Categorize(context.Background(), ops)
	if err != nil || len(result) != len(ops) || len(fake.batches) != 2 {
		t.Fatalf("batches=%v results=%d error=%v", fake.batches, len(result), err)
	}
	if fake.batches[0] >= 400 {
		t.Fatal("text budget exceeded")
	}
}

func TestMLInvalidConfidenceIsNotTrusted(t *testing.T) {
	for _, confidence := range []float64{-1, 2, math.NaN(), math.Inf(1)} {
		fake := &fakeML{answers: map[string]*categorizev1.Classification{"x": {Category: "supplier", Confidence: confidence}}}
		result, err := (&MLCategorizer{Client: fake}).Categorize(context.Background(), outOps("x"))
		if err != nil || result[0].Category != domain.CatUnknown {
			t.Fatalf("accepted confidence %v: %+v %v", confidence, result, err)
		}
	}
}
