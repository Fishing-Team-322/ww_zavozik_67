package product

import (
	"context"
	"strconv"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/jackc/pgx/v5"
)

// The gateway reports the outstanding total, not the original assessment. Once
// an installment is paid, only the unpaid installments share a NEW assessment.
// An unchanged snapshot must not resurrect amounts paid since that snapshot.
func rebalanceTaxOutstanding(incoming, existing []Doc) error {
	previous := map[string]Doc{}
	for _, event := range existing {
		previous[text(event, "external_id")+":"+partKey(event)] = event
	}
	groups := map[string][]Doc{}
	for _, event := range incoming {
		groups[text(event, "external_id")] = append(groups[text(event, "external_id")], event)
	}
	for externalID, parts := range groups {
		unchanged, unpaid := true, []Doc{}
		for _, part := range parts {
			old := previous[externalID+":"+partKey(part)]
			lastHash := text(old, "last_seen_upstream_hash")
			if lastHash == "" {
				lastHash = text(old, "upstream_hash")
			}
			unchanged = unchanged && lastHash == text(part, "upstream_hash")
			if text(old, "status") == "received" || text(old, "matched_operation_id") != "" {
				// Preserve the receipt and its original financial terms, including
				// receipts confirmed by accounting without an imported bank fact.
				part["preserve_receipt"] = true
				continue
			}
			unpaid = append(unpaid, part)
		}
		for _, part := range parts {
			if flag(part, "preserve_receipt") {
				continue
			}
			old := previous[externalID+":"+partKey(part)]
			if unchanged && old != nil {
				part["amount"] = old["amount"]
			}
		}
		if unchanged || len(parts) == 0 || text(parts[0], "status") != "expected" {
			continue
		}
		total := int64(number(parts[0], "upstream_amount_kopecks"))
		if len(unpaid) == 0 && total > 0 {
			return platform.Fail(409, "tax_schedule_conflict", "Все части налога уже оплачены; для нового долга нужен отдельный external_id и срок")
		}
		for i, part := range unpaid {
			amount := total / int64(len(unpaid))
			if int64(i) < total%int64(len(unpaid)) {
				amount++
			}
			part["amount"] = float64(amount) / 100
		}
	}
	return nil
}

func partKey(d Doc) string { return strconv.Itoa(int(number(d, "part"))) }

func loadSourceEvents(ctx context.Context, tx pgx.Tx, cid, sourceID string) ([]Doc, error) {
	rows, err := tx.Query(ctx, `SELECT extra||jsonb_build_object('id',id,'amount',amount,'status',status,'matched_operation_id',matched_operation_id) FROM planned_events WHERE company_id=$1 AND source_id=$2`, cid, sourceID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := []Doc{}
	for rows.Next() {
		var raw []byte
		if err = rows.Scan(&raw); err != nil {
			return nil, err
		}
		result = append(result, store.Decode(raw))
	}
	return result, rows.Err()
}
