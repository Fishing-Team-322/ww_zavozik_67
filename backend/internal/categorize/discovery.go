package categorize

import (
	"context"
	"fmt"
	discovery "github.com/Fishing-Team-322/ww_zavozik_67/backend/gen/categorize/v3"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"math"
	"time"
)

// Discovery combines versioned native categories with a separate forecast hint.
// Confident rules and user corrections retain precedence for financial scope.
type Discovery struct {
	Client    discovery.DiscoveryServiceClient
	Timeout   time.Duration
	BatchSize int
	Rules     Categorizer
	conn      *grpc.ClientConn
}

func DialDiscovery(addr string) (*Discovery, error) {
	if addr == "" {
		return nil, fmt.Errorf("Qwen categorizer address is required")
	}
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()), grpc.WithDefaultCallOptions(grpc.MaxCallRecvMsgSize(16<<20), grpc.MaxCallSendMsgSize(8<<20)))
	if err != nil {
		return nil, err
	}
	return &Discovery{Client: discovery.NewDiscoveryServiceClient(conn), Timeout: 120 * time.Second, BatchSize: 8, Rules: DefaultRules, conn: conn}, nil
}
func (m *Discovery) Close() error {
	if m.conn == nil {
		return nil
	}
	return m.conn.Close()
}
func (m *Discovery) Taxonomy(ctx context.Context) (*discovery.GetTaxonomyResponse, error) {
	ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()
	return m.Client.GetTaxonomy(ctx, &discovery.GetTaxonomyRequest{})
}
func (m *Discovery) Categorize(ctx context.Context, ops []domain.Operation) ([]Result, error) {
	rules := m.Rules
	if rules == nil {
		rules = DefaultRules
	}
	out, err := rules.Categorize(ctx, ops)
	if err != nil {
		return nil, err
	}
	if len(out) != len(ops) {
		return nil, fmt.Errorf("discovery: invalid rules response")
	}
	batch := m.BatchSize
	if batch <= 0 {
		batch = 8
	}
	batch = min(batch, 64)
	for from := 0; from < len(ops); from += batch {
		to := min(from+batch, len(ops))
		req := &discovery.AssignRequest{}
		for _, op := range ops[from:to] {
			req.Operations = append(req.Operations, &discovery.Operation{Id: op.ID, Direction: string(op.Direction), PaymentPurpose: string(op.Purpose), CounterpartyName: string(op.CounterpartyName)})
		}
		timeout := m.Timeout
		if timeout <= 0 {
			timeout = 120 * time.Second
		}
		call, cancel := context.WithTimeout(ctx, timeout)
		resp, e := m.Client.Assign(call, req)
		cancel()
		if e != nil {
			return nil, fmt.Errorf("discovery categorization unavailable: %w", e)
		}
		if resp.GetEmbeddingDim() != 1024 || resp.GetTaxonomyVersion() == "" || len(resp.GetResults()) != to-from {
			return nil, fmt.Errorf("discovery: incompatible response shape/version")
		}
		for j, r := range resp.GetResults() {
			i := from + j
			if r.GetId() != ops[i].ID || len(r.GetEmbedding()) != 1024 {
				return nil, fmt.Errorf("discovery: mismatched operation or embedding")
			}
			if !validDiscoveryStatus(r.GetStatus()) {
				return nil, fmt.Errorf("discovery: invalid assignment status")
			}
			for _, v := range r.GetEmbedding() {
				if math.IsNaN(float64(v)) || math.IsInf(float64(v), 0) {
					return nil, fmt.Errorf("discovery: non-finite embedding")
				}
			}
			if r.Similarity != nil && (math.IsNaN(float64(*r.Similarity)) || math.IsInf(float64(*r.Similarity), 0) || math.Abs(float64(*r.Similarity)) > 1.0001) {
				return nil, fmt.Errorf("discovery: invalid cosine")
			}
			if r.GetStatus() == "assigned" && (r.GetCategoryId() == "" || r.GetCoarseCategoryId() == "" || len(r.GetCategoryPath()) != 2 || r.GetCategoryPath()[0] != r.GetCoarseCategoryId() || r.GetCategoryPath()[1] != r.GetCategoryId()) {
				return nil, fmt.Errorf("discovery: invalid assigned path")
			}
			if r.GetStatus() == "coarse_only" && (r.GetCategoryId() != "" || r.GetCoarseCategoryId() == "" || len(r.GetCategoryPath()) != 1 || r.GetCategoryPath()[0] != r.GetCoarseCategoryId()) {
				return nil, fmt.Errorf("discovery: invalid coarse path")
			}
			if r.GetStatus() != "assigned" && r.GetStatus() != "coarse_only" && (r.GetCategoryId() != "" || r.GetCoarseCategoryId() != "" || len(r.GetCategoryPath()) != 0) {
				return nil, fmt.Errorf("discovery: IDs supplied for abstention")
			}
			hint := domain.Category(r.GetForecastCategory())
			if !knownCategory[hint] {
				return nil, fmt.Errorf("discovery: unknown forecast hint")
			}
			a := &domain.DiscoveredAssignment{Status: r.GetStatus(), CategoryID: r.GetCategoryId(), CategoryTitle: r.GetCategoryTitle(), CoarseCategoryID: r.GetCoarseCategoryId(), CoarseCategoryTitle: r.GetCoarseCategoryTitle(), CategoryPath: append([]string{}, r.GetCategoryPath()...), TaxonomyVersion: resp.GetTaxonomyVersion(), EncoderVersion: resp.GetEncoderVersion(), ScoreKind: resp.GetScoreKind(), ForecastCategory: hint, ProjectionVersion: r.GetForecastProjectionVersion(), ProjectionSource: r.GetForecastProjectionSource()}
			if r.Similarity != nil {
				v := float64(*r.Similarity)
				a.Similarity = &v
			}
			out[i].Discovery = a
			if ops[i].CategoryMethod == domain.MethodUser && knownCategory[ops[i].Category] {
				out[i].Category = ops[i].Category
				out[i].Method = domain.MethodUser
				out[i].Confidence = 1
				continue
			}
			if out[i].Category != domain.CatUnknown && out[i].Category != domain.CatOther {
				continue
			}
			if hint.IsInternal() && a.ProjectionSource != "source_text_evidence_v1" {
				continue
			}
			if !forecastDirection(hint, ops[i].Direction) {
				continue
			}
			out[i].Category = hint
			out[i].Confidence = 0
			out[i].Method = domain.MethodML
			if a.ProjectionSource == "source_text_evidence_v1" {
				out[i].Method = domain.MethodRule
			}
		}
	}
	for i := range out {
		if out[i].Category == domain.CatUnknown {
			out[i].Category = domain.CatOther
			out[i].Method = domain.MethodRule
		}
	}
	return out, nil
}
func validDiscoveryStatus(s string) bool {
	switch s {
	case "assigned", "coarse_only", "unknown", "ambiguous", "insufficient_text":
		return true
	}
	return false
}
func forecastDirection(c domain.Category, d domain.Direction) bool {
	switch c {
	case domain.CatOther, domain.CatLoanPayment, domain.CatOwnTransfer, domain.CatOwnerLoan:
		return true
	case domain.CatRevenueAcquiring, domain.CatRevenueSBP, domain.CatRevenueCash, domain.CatRevenueB2B, domain.CatRevenueMarketplace, domain.CatRefund:
		return d == domain.In
	default:
		return d == domain.Out
	}
}
