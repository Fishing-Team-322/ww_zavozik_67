package product

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"reflect"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/bridge"
	"github.com/jackc/pgx/v5"
)

type onecPlanCounts struct{ Added, Updated, Duplicates int }

// saveOneCPlans runs inside the same transaction as the bank facts. An
// incomplete OData fetch never replaces the last committed state.
func saveOneCPlans(ctx context.Context, tx pgx.Tx, companyID, sourceID string, plans []bridge.PlannedEvent) (onecPlanCounts, error) {
	counts := onecPlanCounts{}
	for _, plan := range plans {
		if plan.SourceKind != "onec_odata" || plan.ExternalID == "" || plan.Direction != "in" && plan.Direction != "out" ||
			plan.TotalKopecks < 0 || plan.PaidKopecks < 0 || plan.RemainingKopecks < 0 || plan.AmountKopecks != plan.RemainingKopecks ||
			plan.RemainingKopecks > plan.TotalKopecks || plan.Currency != "RUB" || plan.DataMode != "live" && plan.DataMode != "mock" && plan.DataMode != "fixture" {
			return counts, platform.Fail(502, "invalid_onec_plan", "1С вернула некорректное обязательство")
		}
		date := plan.Date
		if plan.DueDate != nil {
			date = *plan.DueDate
		}
		if _, err := time.Parse("2006-01-02", date); err != nil {
			return counts, platform.Fail(502, "invalid_onec_plan", "1С вернула некорректную дату обязательства")
		}
		id := idFor(companyID, "onec-plan:"+sourceID+":"+plan.ExternalID+":"+plan.Direction)
		var previous []byte
		err := tx.QueryRow(ctx, "SELECT extra->'onec_plan' FROM planned_events WHERE id=$1 AND company_id=$2 AND source_id=$3 FOR UPDATE", id, companyID, sourceID).Scan(&previous)
		version := int64(1)
		if err == nil {
			var old bridge.PlannedEvent
			if json.Unmarshal(previous, &old) != nil {
				return counts, errors.New("invalid saved 1C plan")
			}
			version = old.Version + 1
			before, after := old, plan
			before.Version, after.Version = 0, 0
			before.ObservedAt, after.ObservedAt = "", ""
			if reflect.DeepEqual(before, after) {
				counts.Duplicates++
				continue
			}
			counts.Updated++
		} else if errors.Is(err, pgx.ErrNoRows) {
			counts.Added++
		} else {
			return counts, err
		}
		plan.Version = version
		forecastEligible := plan.DataMode == "live" && plan.ForecastEligible && plan.DueDate != nil &&
			plan.LinkStatus == "reconciled" && plan.RemainingKopecks > 0
		status := plan.Status
		if forecastEligible {
			status = "expected"
		} else if plan.DataMode != "live" {
			status = "mock"
		} else if plan.DueDate == nil && plan.RemainingKopecks > 0 {
			status = "undated"
		} else if plan.LinkStatus != "reconciled" && plan.RemainingKopecks > 0 {
			status = "needs_reconciliation"
		}
		extra := Doc{
			"onec_plan": plan, "source": "onec_odata", "source_id": sourceID,
			"external_id": plan.ExternalID, "due_date": plan.DueDate,
			"total_kopecks": plan.TotalKopecks, "paid_kopecks": plan.PaidKopecks,
			"remaining_kopecks": plan.RemainingKopecks, "forecast_eligible": forecastEligible,
			"link_status": plan.LinkStatus, "data_mode": plan.DataMode,
			"payment_status":   plan.Status,
			"counterparty_inn": plan.CounterpartyINN, "version": version,
			"additional": forecastEligible,
		}
		amount := fmt.Sprintf("%d.%02d", plan.RemainingKopecks/100, plan.RemainingKopecks%100)
		_, err = tx.Exec(ctx, `INSERT INTO planned_events(id,company_id,source_id,source_kind,event_date,amount,direction,title,category,counterparty_name,probability,status,extra)
VALUES($1,$2,$3,'onec_odata',$4,$5,$6,$7,'other','',1,$8,$9)
ON CONFLICT(id) DO UPDATE SET event_date=EXCLUDED.event_date,amount=EXCLUDED.amount,direction=EXCLUDED.direction,title=EXCLUDED.title,status=EXCLUDED.status,extra=EXCLUDED.extra
WHERE planned_events.company_id=EXCLUDED.company_id AND planned_events.source_id=EXCLUDED.source_id`, id, companyID, sourceID, date, amount, plan.Direction, plan.Title, status, string(store.JSON(extra)))
		if err != nil {
			return counts, err
		}
		_, err = tx.Exec(ctx, "INSERT INTO onec_plan_versions(company_id,source_id,external_id,direction,version,payload) VALUES($1,$2,$3,$4,$5,$6)", companyID, sourceID, plan.ExternalID, plan.Direction, version, string(store.JSON(plan)))
		if err != nil {
			return counts, err
		}
	}
	return counts, nil
}
