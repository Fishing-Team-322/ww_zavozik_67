package forecast

import "slices"

// Clone — глубокая копия: сценарии меняют копию, базовый прогноз не трогают.
func (r Result) Clone() Result {
	out := r
	out.Dates = slices.Clone(r.Dates)
	out.Deterministic = slices.Clone(r.Deterministic)
	out.Stochastic.Dates = slices.Clone(r.Stochastic.Dates)
	out.Stochastic.Inflow = clone2(r.Stochastic.Inflow)
	out.Stochastic.Outflow = clone2(r.Stochastic.Outflow)
	out.Balances = clone2(r.Balances)
	return out
}

func clone2(xs [][]float64) [][]float64 {
	out := make([][]float64, len(xs))
	for i := range xs {
		out[i] = slices.Clone(xs[i])
	}
	return out
}
