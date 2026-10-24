package categorize

import (
	"context"
	"fmt"
	"math"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	categorizev1 "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/categorize/v1"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// MLCategorizer — звено цепочки поверх Python-классификатора
// (proto/categorize/v1, CategorizerService.Classify). Ставится после правил:
//
//	Chain{Steps: []Categorizer{DefaultRules, ml}, Threshold: 0.5}
//
// Уверенные правила остаются, модель добирает остальное. Ответ модели —
// только категория из domain.AllCategories; всё прочее считаем «не знаю»
// (Category пустая) — новых категорий не бывает.
type MLCategorizer struct {
	Client categorizev1.CategorizerServiceClient
	// BatchSize — операций в одном запросе (0 — 5000).
	BatchSize int
	// Timeout на один запрос (0 — 30 с).
	Timeout time.Duration
	// MinConfidence — ниже этой уверенности ответ модели не берём (Category
	// пустая, цепочка в конце даст other).
	MinConfidence float64
	// FailOpen: ML недоступен → не ошибка, а пустые результаты (останутся
	// правила / other). Прогноз не должен падать из-за ML-сервиса.
	FailOpen bool
	// OnError вызывается при ошибке ML в режиме FailOpen (метрики/лог без ПДн).
	OnError func(error)

	conn *grpc.ClientConn
}

// DialMLCategorizer не ходит в сеть: соединение ленивое. Внутри docker-сети
// без TLS; наружу ML-сервис не публикуется. По умолчанию FailOpen.
func DialMLCategorizer(addr string) (*MLCategorizer, error) {
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()),
		grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(64<<20), grpc.MaxCallSendMsgSize(64<<20)))
	if err != nil {
		return nil, fmt.Errorf("categorize ml: dial %s: %w", addr, err)
	}
	return &MLCategorizer{Client: categorizev1.NewCategorizerServiceClient(conn), FailOpen: true, conn: conn}, nil
}

func (m *MLCategorizer) Close() error {
	if m.conn == nil {
		return nil
	}
	return m.conn.Close()
}

var knownCategory = func() map[domain.Category]bool {
	out := make(map[domain.Category]bool, len(domain.AllCategories))
	for _, c := range domain.AllCategories {
		out[c] = true
	}
	return out
}()

func (m *MLCategorizer) Categorize(ctx context.Context, ops []domain.Operation) ([]Result, error) {
	out := make([]Result, len(ops))
	batch := m.BatchSize
	if batch <= 0 {
		batch = 5000
	}
	for from := 0; from < len(ops); from += batch {
		to := min(from+batch, len(ops))
		if err := m.classify(ctx, ops[from:to], out[from:to]); err != nil {
			if !m.FailOpen || ctx.Err() != nil {
				return nil, err
			}
			if m.OnError != nil {
				m.OnError(err)
			}
			clear(out[from:to])
		}
	}
	return out, nil
}

func (m *MLCategorizer) classify(ctx context.Context, ops []domain.Operation, out []Result) error {
	timeout := m.Timeout
	if timeout <= 0 {
		timeout = 30 * time.Second
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	req := &categorizev1.ClassifyRequest{Operations: make([]*categorizev1.Operation, len(ops))}
	for i, op := range ops {
		req.Operations[i] = &categorizev1.Operation{
			Id:               op.ID,
			Direction:        string(op.Direction),
			Amount:           op.Amount.Float(),
			CounterpartyInn:  string(op.CounterpartyINN),
			CounterpartyName: string(op.CounterpartyName),
			PaymentPurpose:   string(op.Purpose),
		}
	}
	resp, err := m.Client.Classify(ctx, req)
	if err != nil {
		return fmt.Errorf("categorize ml: %w", err)
	}
	res := resp.GetResults()
	if len(res) != len(ops) {
		return fmt.Errorf("categorize ml: %d results for %d operations", len(res), len(ops))
	}
	for i, r := range res {
		if r.GetId() != ops[i].ID {
			return fmt.Errorf("categorize ml: response order mismatch")
		}
		c := domain.Category(r.GetCategory())
		conf := r.GetConfidence()
		if !knownCategory[c] || math.IsNaN(conf) || math.IsInf(conf, 0) || conf < m.MinConfidence {
			out[i] = Result{}
			continue
		}
		out[i] = Result{Category: c, Confidence: min(max(conf, 0), 1), Method: domain.MethodML}
	}
	return nil
}
