package product

import (
	"context"
	"math"
	"sort"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/ingest"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

// Detection is a reviewable heuristic, never an automatic confirmation.
func (s *Service) detectRecurring(ctx context.Context, uid, cid string) error {
	rows, e := s.DB.ProductList(ctx, uid, cid, "operation")
	if e != nil {
		return e
	}
	groups := map[string][]Doc{}
	for _, d := range rows {
		if flag(d, "is_internal") || flag(d, "is_duplicate") {
			continue
		}
		key := cpKey(d) + ":" + text(d, "direction") + ":" + text(d, "category")
		groups[key] = append(groups[key], d)
	}
	existing, e := s.DB.ProductList(ctx, uid, cid, "recurring")
	if e != nil {
		return e
	}
	seen := map[string]bool{}
	for _, p := range existing {
		seen[text(p, "id")] = true
	}
	for key, group := range groups {
		if len(existing) >= 200 {
			break
		}
		if len(group) < 4 {
			continue
		}
		sort.Slice(group, func(i, j int) bool { return date(group[i]["op_date"]) < date(group[j]["op_date"]) })
		intervals, amounts := []float64{}, []float64{}
		for i, d := range group {
			amounts = append(amounts, number(d, "amount"))
			if i > 0 {
				a, _ := day(date(group[i-1]["op_date"]))
				b, _ := day(date(d["op_date"]))
				if b.After(a) {
					intervals = append(intervals, b.Sub(a).Hours()/24)
				}
			}
		}
		if len(intervals) < 3 {
			continue
		}
		sort.Float64s(intervals)
		sort.Float64s(amounts)
		interval, amount := intervals[len(intervals)/2], amounts[len(amounts)/2]
		period := ""
		switch {
		case interval >= 6 && interval <= 8:
			period = "weekly"
		case interval >= 13 && interval <= 15:
			period = "biweekly"
		case interval >= 27 && interval <= 33:
			period = "monthly"
		case interval >= 86 && interval <= 95:
			period = "quarterly"
		}
		if period == "" || amount <= 0 {
			continue
		}
		consistent := 0
		for _, v := range amounts {
			if math.Abs(v-amount) <= math.Max(1, amount*.1) {
				consistent++
			}
		}
		if float64(consistent)/float64(len(amounts)) < .8 {
			continue
		}
		id := idFor(cid, "detected:"+key)
		if seen[id] {
			continue
		}
		last := group[len(group)-1]
		lastDate, _ := day(date(last["op_date"]))
		next := lastDate
		for i := 0; i < 4000 && !next.After(today()); i++ {
			next = nextOccurrence(next, period, lastDate.Day())
		}
		d := Doc{"id": id, "title": text(last, "counterparty_name"), "category": last["category"], "direction": last["direction"], "counterparty_name": last["counterparty_name"], "counterparty_inn": last["counterparty_inn"], "period": period, "day_of_month": float64(lastDate.Day()), "amount": amount, "baseline_amount": amount, "amount_spread": amounts[len(amounts)-1] - amounts[0], "next_date": next.Format(domain.DateLayout), "confirmed": nil, "active": true, "origin": "detected"}
		if d["title"] == "" {
			d["title"] = "Регулярный платёж"
		}
		if _, e = s.DB.ProductSave(ctx, uid, cid, "recurring", id, d, true); e != nil {
			return e
		}
		existing = append(existing, d)
	}
	return nil
}
func (s *Service) reconcileFacts(ctx context.Context, uid, cid string) error {
	tx, e := s.DB.Pool.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(ctx)
	var locked string
	if e = tx.QueryRow(ctx, "SELECT c.id::text FROM companies c JOIN memberships m ON m.company_id=c.id WHERE c.id=$1 AND m.user_id=$2 AND m.role='owner' FOR UPDATE OF c", cid, uid).Scan(&locked); e != nil {
		return e
	}
	rows, e := s.DB.ProductList(ctx, uid, cid, "operation")
	if e != nil {
		return e
	}
	ops := domainOperations(rows)
	if len(ops) == 0 {
		return nil
	}
	asOf := ops[len(ops)-1].Date
	coverage := ingest.DailyFlows(ops, ops[0].Date, asOf, nil)
	known := map[string]bool{}
	for _, d := range coverage {
		known[d.Date.Format(domain.DateLayout)] = !d.Missing
	}
	events, e := s.DB.ProductList(ctx, uid, cid, "event")
	if e != nil {
		return e
	}
	used := map[string]bool{}
	settlements, e := tx.Query(ctx, "SELECT operation_id FROM operation_settlements WHERE company_id=$1", cid)
	if e != nil {
		return e
	}
	for settlements.Next() {
		var id string
		if e = settlements.Scan(&id); e != nil {
			settlements.Close()
			return e
		}
		used[id] = true
	}
	e = settlements.Err()
	settlements.Close()
	if e != nil {
		return e
	}
	for _, d := range events {
		if id := text(d, "matched_operation_id"); id != "" {
			used[id] = true
		}
	}
	candidates := map[string][]Doc{}
	possibleUses := map[string]int{}
	for _, event := range events {
		if !in(text(event, "status"), "expected missed") {
			continue
		}
		dt, err := day(date(event["event_date"]))
		if err != nil {
			return err
		}
		matches := []Doc{}
		for _, op := range rows {
			if used[text(op, "id")] || flag(op, "is_duplicate") || flag(op, "is_internal") || text(op, "direction") != text(event, "direction") || math.Abs(number(op, "amount")-number(event, "amount")) > .011 {
				continue
			}
			taxMatch := text(event, "source_kind") == "tax_calendar" && text(op, "category") == "tax"
			if !taxMatch && !samePaymentCounterparty(event, op) {
				continue
			}
			actual, _ := day(date(op["op_date"]))
			window := 3.0
			if in(text(event, "source_kind"), "manual invoice contract tax_calendar") {
				window = 31
			}
			if math.Abs(actual.Sub(dt).Hours()/24) <= window {
				matches = append(matches, op)
				possibleUses[text(op, "id")]++
			}
		}
		candidates[text(event, "id")] = matches
	}
	changed := false
	for _, event := range events {
		if !in(text(event, "status"), "expected missed") {
			continue
		}
		dt, err := day(date(event["event_date"]))
		if err != nil {
			return err
		}
		matches := candidates[text(event, "id")]
		if len(matches) == 1 && possibleUses[text(matches[0], "id")] == 1 {
			match := matches[0]
			tag, err := tx.Exec(ctx, `INSERT INTO operation_settlements(company_id,operation_id,event_id,source_kind,document_id) VALUES($1,$2,$3,$4,$5) ON CONFLICT(company_id,operation_id) DO NOTHING`, cid, match["id"], event["id"], text(event, "source_kind"), text(event, "document_id"))
			if err != nil {
				return err
			}
			if tag.RowsAffected() == 0 {
				continue
			}
			used[text(match, "id")] = true
			_, e = tx.Exec(ctx, "UPDATE planned_events SET status='received',matched_operation_id=$2,extra=extra||jsonb_build_object('_revision',COALESCE((extra->>'_revision')::int,0)+1) WHERE id=$1 AND company_id=$3 AND status IN ('expected','missed')", event["id"], match["id"], cid)
			if e != nil {
				return e
			}
			changed = true
			if text(event, "source_kind") == "invoice" {
				_, e = tx.Exec(ctx, `UPDATE product_documents SET data=data||jsonb_build_object('_revision',COALESCE((data->>'_revision')::int,0)+1,'paid_amount',LEAST((data->>'amount')::numeric,COALESCE((data->>'paid_amount')::numeric,0)+$2::numeric),'paid_at',$3::text,'status','paid'),updated_at=now() WHERE id::text=$1 AND company_id=$4 AND kind='invoice'`, text(event, "document_id"), number(match, "amount"), date(match["op_date"]), cid)
				if e != nil {
					return e
				}
			}
			if text(event, "source_kind") == "contract" {
				if e = store.ApplyContractReceipt(ctx, tx, cid, text(event, "document_id"), text(event, "id")); e != nil {
					return e
				}
			}
		} else if len(matches) == 0 && text(event, "status") == "expected" && dt.Before(asOf) && known[dt.Format(domain.DateLayout)] {
			_, e = tx.Exec(ctx, "UPDATE planned_events SET status='missed',extra=extra||jsonb_build_object('_revision',COALESCE((extra->>'_revision')::int,0)+1) WHERE id=$1 AND company_id=$2 AND status='expected'", event["id"], cid)
			if e != nil {
				return e
			}
			changed = true
		}
	}
	if changed {
		if _, e = tx.Exec(ctx, "UPDATE companies SET data_revision=data_revision+1 WHERE id=$1", cid); e != nil {
			return e
		}
	}
	return tx.Commit(ctx)
}
func samePaymentCounterparty(event, operation Doc) bool {
	expectedINN := strings.TrimSpace(text(event, "counterparty_inn"))
	actualINN := strings.TrimSpace(text(operation, "counterparty_inn"))
	if expectedINN != "" && actualINN != "" {
		return expectedINN == actualINN
	}
	name := text(event, "counterparty_name")
	return name != "" && name == text(operation, "counterparty_name")
}
func (s *Service) evaluateSignals(ctx context.Context, uid, cid string) error {
	rows, e := s.DB.ProductList(ctx, uid, cid, "operation")
	if e != nil {
		return e
	}
	amounts := []float64{}
	for _, d := range rows {
		if text(d, "direction") == "out" && !flag(d, "is_internal") {
			amounts = append(amounts, number(d, "amount"))
		}
	}
	if len(amounts) < 5 {
		return nil
	}
	sort.Float64s(amounts)
	median := amounts[len(amounts)/2]
	threshold := math.Max(100000, median*5)
	for _, d := range rows {
		if text(d, "direction") != "out" || number(d, "amount") <= threshold || flag(d, "is_internal") {
			continue
		}
		id := idFor(cid, "signal:large_spend:"+text(d, "id"))
		if _, e = s.DB.ProductGet(ctx, uid, "signal", id); e == nil {
			continue
		}
		signal := Doc{"id": id, "kind": "large_spend", "severity": "warning", "amount": d["amount"], "status": "new", "resolution": nil, "operation_id": d["id"], "explanation": Doc{"metric": "outflow_amount", "value": d["amount"], "normal_range": []float64{0, threshold}, "method": "five_times_observed_median_with_100000_floor", "not_verdict": true}}
		if _, e = s.DB.ProductSave(ctx, uid, cid, "signal", id, signal, true); e != nil {
			return e
		}
	}
	return nil
}
