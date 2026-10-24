package ingest

import (
	"fmt"
	"math"
	"sort"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

type DedupReport struct {
	Removed     int `json:"duplicates_removed"`
	Unconfirmed int `json:"duplicate_candidates_retained"`
}

// Deduplicate preserves legitimate equal payments. Different operation IDs
// are not proof of a duplicate: remove repeated economic rows only when doing
// so exactly reconciles the day's balance with the previous observed balance.
// A first-day duplicate cannot be established from balance_eod alone.
func Deduplicate(input []domain.Operation) ([]domain.Operation, DedupReport) {
	ops := append([]domain.Operation(nil), input...)
	SortOps(ops)
	sort.SliceStable(ops, func(i, j int) bool { return ops[i].CompanyID < ops[j].CompanyID })
	out := make([]domain.Operation, 0, len(ops))
	var report DedupReport
	var previous *domain.Money
	var previousCompany string
	movement := 0.0
	for start := 0; start < len(ops); {
		end := start + 1
		for end < len(ops) && ops[end].CompanyID == ops[start].CompanyID && domain.Day(ops[end].Date).Equal(domain.Day(ops[start].Date)) {
			end++
		}
		if ops[start].CompanyID != previousCompany {
			previous = nil
			movement = 0
			previousCompany = ops[start].CompanyID
		}
		day := ops[start:end]
		var balance *domain.Money
		conflict := false
		net, redundant := 0.0, 0.0
		seen := map[string]bool{}
		candidates := map[int]bool{}
		for i, op := range day {
			net += op.Signed().Float()
			if op.BalanceEOD != nil {
				if balance != nil && math.Abs(balance.Float()-op.BalanceEOD.Float()) > 0.011 {
					conflict = true
				}
				balance = op.BalanceEOD
			}
			key := fingerprint(op)
			if seen[key] {
				candidates[i] = true
				redundant += op.Signed().Float()
			}
			seen[key] = true
		}
		remove := previous != nil && balance != nil && !conflict && len(candidates) > 0 &&
			math.Abs(balance.Float()-previous.Float()-(movement+net)) > 0.011 &&
			math.Abs(balance.Float()-previous.Float()-(movement+net-redundant)) <= 0.011
		for i, op := range day {
			if remove && candidates[i] {
				report.Removed++
				continue
			}
			out = append(out, op)
			if candidates[i] {
				report.Unconfirmed++
			}
		}
		movement += net
		if remove {
			movement -= redundant
		}
		if balance != nil {
			b := *balance
			previous = &b
			movement = 0
		}
		start = end
	}
	return out, report
}

func fingerprint(o domain.Operation) string {
	return fmt.Sprintf("%s\x00%s\x00%.2f\x00%s\x00%s\x00%s\x00%s", o.CompanyID,
		domain.Day(o.Date).Format(time.DateOnly), o.Amount.Float(), o.Direction,
		string(o.CounterpartyINN), string(o.CounterpartyName), string(o.Purpose))
}
