package forecast

import (
	"math"

	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// Keep the Go fallback and Python service on the same input contract. Invalid
// input must not become a plausible zero forecast when Python is unavailable.
func validateRequest(req StochasticRequest) error {
	if req.Horizon < 1 || req.Horizon > 366 || req.NPaths < 1 || req.NPaths > 5000 || req.Horizon*req.NPaths > 1_000_000 {
		return status.Error(codes.InvalidArgument, "forecast: invalid horizon or number of paths")
	}
	if req.Seed < 0 || (req.FlowScope != "" && req.FlowScope != BusinessFlowScope) {
		return status.Error(codes.InvalidArgument, "forecast: invalid seed or flow scope")
	}
	if len(req.History) == 0 || len(req.History) > 3650 {
		return status.Error(codes.InvalidArgument, "forecast: history must contain 1..3650 days")
	}
	observed := false
	for i, f := range req.History {
		day := domain.Day(f.Date)
		if day.Year() < 1 || day.Year() > 9999 || (i > 0 && !day.Equal(domain.Day(req.History[i-1].Date).AddDate(0, 0, 1))) {
			return status.Error(codes.InvalidArgument, "forecast: history must contain consecutive supported dates")
		}
		if !finiteFlow(f.Inflow.Float()) || !finiteFlow(f.Outflow.Float()) {
			return status.Error(codes.InvalidArgument, "forecast: flows must be finite and in [0, 1e15]")
		}
		for category, amount := range f.ByCategory {
			known := false
			for _, c := range domain.AllCategories {
				known = known || category == c
			}
			if !known || !finiteFlow(math.Abs(amount.Float())) {
				return status.Error(codes.InvalidArgument, "forecast: invalid category flow")
			}
		}
		observed = observed || !f.Missing
	}
	last := domain.Day(req.History[len(req.History)-1].Date)
	if last.AddDate(0, 0, req.Horizon).Year() > 9999 {
		return status.Error(codes.InvalidArgument, "forecast: forecast dates exceed supported range")
	}
	if !observed {
		return status.Error(codes.FailedPrecondition, "forecast: history contains no observed days")
	}
	if len(req.Transactions) > 100000 {
		return status.Error(codes.InvalidArgument, "forecast: too many history transactions")
	}
	seen := map[string]bool{}
	for i, tx := range req.Transactions {
		if tx.ID == "" || seen[tx.ID] || tx.Direction != domain.In && tx.Direction != domain.Out || !finiteFlow(tx.Amount.Float()) || tx.Date.Before(domain.Day(req.History[0].Date)) || tx.Date.After(last) || i > 0 && tx.Date.Before(req.Transactions[i-1].Date) {
			return status.Error(codes.InvalidArgument, "forecast: invalid ordered transaction history")
		}
		seen[tx.ID] = true
	}
	return nil
}

func finiteFlow(v float64) bool {
	return !math.IsNaN(v) && !math.IsInf(v, 0) && v >= 0 && v <= 1e15
}
