// mlcheck verifies real Go clients against a running Python gRPC server.
// No database, HTTP handlers, or external financial data are involved.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"reflect"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/forecast"
)

func main() {
	addr := flag.String("ml", "127.0.0.1:50051", "gRPC address")
	flag.Parse()
	if err := check(*addr); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
func check(addr string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	ml, err := forecast.DialML(addr)
	if err != nil {
		return err
	}
	defer ml.Close()
	cats, err := categorize.DialMLCategorizer(addr)
	if err != nil {
		return err
	}
	defer cats.Close()
	cats.FailOpen = false
	labels, err := (categorize.Hybrid{ML: cats}).Categorize(ctx, []domain.Operation{
		{ID: "a", Direction: domain.Out, Amount: 1000, Purpose: "Зарплата на кошелек цифрового рубля", CounterpartyName: "ПАО Банк"},
		{ID: "b", Direction: domain.Out, Amount: 1000, Purpose: "Перечисление остатка в связи с закрытием счета", CounterpartyName: "ПАО Банк"},
	})
	if err != nil {
		return err
	}
	if labels[0].Category != domain.CatSalary || labels[1].Category != domain.CatOwnTransfer {
		return fmt.Errorf("unexpected classification: %s %s", labels[0].Category, labels[1].Category)
	}
	history := make([]domain.DailyFlow, 120)
	start := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	for i := range history {
		d := start.AddDate(0, 0, i)
		history[i].Date = d
		if d.Weekday() != time.Saturday && d.Weekday() != time.Sunday {
			history[i].Inflow = 10000
			history[i].Outflow = 7000
		}
	}
	req := forecast.StochasticRequest{CompanyID: "integration-fixture", Model: "ensemble", History: history, Horizon: 30, NPaths: 64, Seed: 42, FlowScope: "business_without_internal_transfers"}
	a, err := ml.Forecast(ctx, req)
	if err != nil {
		return err
	}
	b, err := ml.Forecast(ctx, req)
	if err != nil {
		return err
	}
	if !reflect.DeepEqual(a.Inflow, b.Inflow) || !reflect.DeepEqual(a.Outflow, b.Outflow) {
		return fmt.Errorf("non-reproducible seeded forecast")
	}
	if a.ModelVersion == "" || a.FlowScope != req.FlowScope {
		return fmt.Errorf("missing model metadata")
	}
	if a.ModelUsed != "ensemble" {
		return fmt.Errorf("trained ensemble was not used")
	}
	req.Model = "auto"
	for i := range req.History {
		req.History[i].Inflow = 0
		req.History[i].Outflow = 100
	}
	fallback, err := ml.Forecast(ctx, req)
	if err != nil {
		return err
	}
	if fallback.ModelUsed != "seasonal_naive" || !fallback.FallbackUsed || !fallback.LowConfidence {
		return fmt.Errorf("out-of-domain fallback not exposed")
	}
	req.FlowScope = "residual_only"
	if _, err = ml.Forecast(ctx, req); err == nil {
		return fmt.Errorf("unsupported scope accepted")
	}
	fmt.Printf("PASS: classifier + hybrid, forecast %s, 64x30 paths, reproducibility, scope validation, auto fallback; version %s\n", a.ModelUsed, a.ModelVersion)
	return nil
}
