package store

import (
	"context"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/jackc/pgx/v5"
)

// Explicitly identifying an existing payment is safer than asking the owner
// whether an opaque model has already predicted a particular invoice.
func validateInvoiceReplacement(ctx context.Context, tx pgx.Tx, cid, id string, d Doc) error {
	ref, _ := d["replaces_event_id"].(string)
	if ref == "" {
		return nil
	}
	if d["additional"] != true {
		return platform.Fail(400, "invalid_replacement", "Уточняющий счёт должен участвовать в прогнозе")
	}
	var raw []byte
	if err := tx.QueryRow(ctx, `SELECT extra||to_jsonb(e) FROM planned_events e WHERE company_id=$1 AND id::text=$2 AND source_kind IN ('manual','recurring') FOR UPDATE`, cid, ref).Scan(&raw); err != nil {
		return dbError(err)
	}
	target := Decode(raw)
	direction := "out"
	if d["direction"] == "issued" {
		direction = "in"
	}
	if target["direction"] != direction {
		return platform.Fail(400, "invalid_replacement", "Направление счёта отличается от выбранного платежа")
	}
	settledBy, _ := target["replacement_settled_by"].(string)
	if ((target["status"] != "expected" && target["status"] != "missed") || target["matched_operation_id"] != nil) && settledBy != id {
		return platform.Fail(409, "settled_payment", "Выбранный платёж уже оплачен или отменён")
	}
	if target["additional"] != true {
		var detected bool
		if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM recurring_patterns WHERE company_id=$1 AND id::text=$2 AND confirmed AND active AND extra->>'origin'='detected')`, cid, target["recurring_id"]).Scan(&detected); err != nil {
			return dbError(err)
		}
		if !detected {
			return platform.Fail(400, "invalid_replacement", "Этот платёж не имеет отдельной суммы в прогнозе. Выберите новый платёж")
		}
	}
	var used bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM product_documents WHERE company_id=$1 AND kind='invoice' AND id::text<>$2 AND data->>'replaces_event_id'=$3)`, cid, id, ref).Scan(&used); err != nil {
		return dbError(err)
	}
	if used {
		return platform.Fail(409, "payment_already_replaced", "Этот платёж уже уточнён другим счётом")
	}
	actualINN, _ := d["counterparty_inn"].(string)
	expectedINN, _ := target["counterparty_inn"].(string)
	for _, key := range []string{"counterparty_name", "counterparty_inn"} {
		actual, _ := d[key].(string)
		expected, _ := target[key].(string)
		compare := key == "counterparty_inn" || strings.TrimSpace(actualINN) == "" || strings.TrimSpace(expectedINN) == ""
		if compare && actual != "" && expected != "" && !strings.EqualFold(strings.TrimSpace(actual), strings.TrimSpace(expected)) {
			return platform.Fail(400, "invalid_replacement", "Контрагент отличается от выбранного платежа")
		}
		if actual == "" {
			d[key] = expected
		}
	}
	return nil
}

func guardReplacedEvent(ctx context.Context, tx pgx.Tx, cid, id string) error {
	var referenced bool
	if err := tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM product_documents WHERE company_id=$1 AND kind='invoice' AND data->>'replaces_event_id'=$2)`, cid, id).Scan(&referenced); err != nil {
		return dbError(err)
	}
	if referenced {
		return platform.Fail(409, "managed_resource", "Этот платёж уточнён счётом. Измените или удалите сам счёт.")
	}
	return nil
}
