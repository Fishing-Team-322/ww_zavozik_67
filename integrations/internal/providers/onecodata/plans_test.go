package onecodata_test

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/service"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func planFixture(base string) onecodata.PlanConfig {
	fields := onecodata.InvoiceFields{ExternalID: "Ref_Key", Number: "Number", DocumentDate: "Date", DueDate: "DueDate", Amount: "Amount", Posted: "Posted", Deleted: "DeletionMark", OrganizationKey: "Organization_Key", SourceVersion: "DataVersion"}
	return onecodata.PlanConfig{
		BaseURL: base, CompanyID: "demo-company", DataMode: "mock", OrganizationIDs: []string{"org-1"},
		Invoices: []onecodata.InvoiceSource{
			{EntitySet: "Document_CustomerInvoice", Direction: "in", Fields: fields},
			{EntitySet: "Document_SupplierInvoice", Direction: "out", Fields: fields},
		},
		Payments: []onecodata.PaymentSource{
			{EntitySet: "Document_Receipt_Detail", InvoiceEntitySet: "Document_CustomerInvoice", Fields: onecodata.PaymentFields{ExternalID: "Ref_Key", LineNumber: "LineNumber", InvoiceKey: "Invoice_Key", Amount: "Amount", Posted: "Posted"}},
			{EntitySet: "Document_Payment_Detail", InvoiceEntitySet: "Document_SupplierInvoice", Fields: onecodata.PaymentFields{ExternalID: "Ref_Key", LineNumber: "LineNumber", InvoiceKey: "Invoice_Key", Amount: "Amount", Posted: "Posted"}},
		},
	}
}

func findPlan(t *testing.T, events []contracts.PlannedEvent, suffix string) contracts.PlannedEvent {
	t.Helper()
	for _, event := range events {
		if strings.HasSuffix(event.ExternalID, suffix) {
			return event
		}
	}
	t.Fatalf("event %s not found", suffix)
	return contracts.PlannedEvent{}
}

func TestPlannedSnapshotPartialChangeCancelAndRepeat(t *testing.T) {
	due := "2026-11-05"
	paid := "100000.00"
	cancelOut := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.HasSuffix(r.URL.Path, "Document_Receipt_Detail") && r.URL.Query().Get("$skiptoken") == "":
			fmt.Fprintf(w, `{"d":{"results":[{"Ref_Key":"payment-1","LineNumber":"1","Invoice_Key":"invoice-in","Amount":%s,"Posted":true}],"__next":"?$skiptoken=page2"}}`, paid)
		case strings.HasSuffix(r.URL.Path, "Document_Receipt_Detail"):
			fmt.Fprint(w, `{"d":{"results":[{"Ref_Key":"payment-1","LineNumber":"1","Invoice_Key":"invoice-in","Amount":100000,"Posted":true}]}}`)
		case strings.HasSuffix(r.URL.Path, "Document_Payment_Detail"):
			fmt.Fprint(w, `{"value":[]}`)
		case strings.HasSuffix(r.URL.Path, "Document_CustomerInvoice"):
			fmt.Fprintf(w, `{"value":[{"Ref_Key":"invoice-in","Number":"10","Date":"2026-10-20","DueDate":%q,"Amount":350000,"Posted":true,"DeletionMark":false,"Organization_Key":"org-1","DataVersion":"v1"},{"Ref_Key":"foreign","Number":"11","Date":"2026-10-20","Amount":1,"Posted":true,"Organization_Key":"org-2"}]}`, due)
		case strings.HasSuffix(r.URL.Path, "Document_SupplierInvoice"):
			fmt.Fprintf(w, `{"value":[{"Ref_Key":"invoice-out","Number":"12","Date":"2026-10-20","DueDate":"2026-11-06","Amount":180000,"Posted":true,"DeletionMark":%t,"Organization_Key":"org-1"}]}`, cancelOut)
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	cfg := planFixture(srv.URL + "/odata/standard.odata/")
	memory := store.NewMemory()
	importer := service.Importer{Store: memory}
	client := onecodata.Client{}
	first, err := importer.OneCPlans(context.Background(), client, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if first.Stats.Accepted != 2 || first.Stats.Rejected != 1 || len(first.PlannedEvents) != 2 {
		t.Fatalf("first batch: %+v", first)
	}
	in := findPlan(t, first.PlannedEvents, ":invoice-in")
	if in.AmountKopecks != 25_000_000 || in.TotalKopecks != 35_000_000 || in.PaidKopecks != 10_000_000 || in.RemainingKopecks != 25_000_000 || in.Status != "partially_paid" || in.Direction != "in" || in.DueDate == nil || *in.DueDate != due || !in.ForecastEligible || in.Version != 1 || in.DataMode != "mock" {
		t.Fatalf("partial: %+v", in)
	}
	out := findPlan(t, first.PlannedEvents, ":invoice-out")
	if out.AmountKopecks != 18_000_000 || out.Direction != "out" || out.Status != "expected" {
		t.Fatalf("outgoing: %+v", out)
	}
	second, err := importer.OneCPlans(context.Background(), client, cfg)
	if err != nil || second.Stats.Accepted != 0 || second.Stats.Duplicates != 2 || len(memory.Plans("demo-company")) != 2 {
		t.Fatalf("repeat: %+v, %v", second.Stats, err)
	}
	due = "2026-11-19"
	cancelOut = true
	third, err := importer.OneCPlans(context.Background(), client, cfg)
	if err != nil || third.Stats.Accepted != 2 {
		t.Fatalf("update: %+v, %v", third.Stats, err)
	}
	in = findPlan(t, third.PlannedEvents, ":invoice-in")
	out = findPlan(t, third.PlannedEvents, ":invoice-out")
	if in.Version != 2 || *in.DueDate != due || out.Version != 2 || out.Status != "cancelled" || out.AmountKopecks != 0 || out.ForecastEligible {
		t.Fatalf("updates: %+v %+v", in, out)
	}
	paid = "350000.00"
	fourth, err := importer.OneCPlans(context.Background(), client, cfg)
	if err != nil || fourth.Stats.Accepted != 1 || fourth.Stats.Duplicates != 1 {
		t.Fatalf("paid: %+v, %v", fourth.Stats, err)
	}
	in = findPlan(t, fourth.PlannedEvents, ":invoice-in")
	if in.Version != 3 || in.Status != "paid" || in.RemainingKopecks != 0 || in.ForecastEligible {
		t.Fatalf("paid event: %+v", in)
	}
}

func TestPlanWithoutReliablePaymentLinkIsNotForecastEligible(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		fmt.Fprint(w, `{"value":[{"Ref_Key":"invoice-1","Number":"1","Date":"2026-10-20","DueDate":"2026-11-05","Amount":1000,"Posted":true,"Organization_Key":"org-1"}]}`)
	}))
	defer srv.Close()
	cfg := planFixture(srv.URL + "/odata/")
	cfg.Invoices = cfg.Invoices[:1]
	cfg.Payments = nil
	batch, err := (onecodata.Client{}).FetchPlans(context.Background(), cfg)
	if err != nil || len(batch.PlannedEvents) != 1 || batch.PlannedEvents[0].LinkStatus != "unmatched" || batch.PlannedEvents[0].ForecastEligible {
		t.Fatalf("unmatched: %+v, %v", batch, err)
	}
}

func TestPlanPaymentDetailRequiresPostedParent(t *testing.T) {
	posted := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case strings.HasSuffix(r.URL.Path, "Document_Receipt"):
			fmt.Fprintf(w, `{"value":[{"Ref_Key":"payment-1","Posted":%t,"Organization_Key":"org-1"}]}`, posted)
		case strings.HasSuffix(r.URL.Path, "Document_Receipt_Detail"):
			fmt.Fprint(w, `{"value":[{"Ref_Key":"payment-1","LineNumber":"1","Invoice_Key":"invoice-1","Amount":100,"Posted":true}]}`)
		default:
			fmt.Fprint(w, `{"value":[{"Ref_Key":"invoice-1","Number":"1","Date":"2026-10-20","DueDate":"2026-11-05","Amount":350,"Posted":true,"Organization_Key":"org-1"}]}`)
		}
	}))
	defer srv.Close()
	cfg := planFixture(srv.URL + "/odata/")
	cfg.Invoices = cfg.Invoices[:1]
	cfg.Payments = cfg.Payments[:1]
	cfg.Payments[0].Fields.Posted = ""
	cfg.Payments[0].Parent = &onecodata.PaymentParent{EntitySet: "Document_Receipt", ExternalID: "Ref_Key", Posted: "Posted", OrganizationKey: "Organization_Key"}
	first, err := (onecodata.Client{}).FetchPlans(context.Background(), cfg)
	if err != nil || len(first.PlannedEvents) != 1 || first.PlannedEvents[0].PaidKopecks != 0 {
		t.Fatalf("unposted parent: %+v, %v", first, err)
	}
	posted = true
	second, err := (onecodata.Client{}).FetchPlans(context.Background(), cfg)
	if err != nil || len(second.PlannedEvents) != 1 || second.PlannedEvents[0].PaidKopecks != 10_000 {
		t.Fatalf("posted parent: %+v, %v", second, err)
	}
}

func TestPlanUpstreamErrorsAndConfig(t *testing.T) {
	cfg := planFixture("https://example.org/odata/")
	cfg.BaseURL = "http://example.org/odata/"
	if !errors.Is(cfg.Validate(), onecodata.ErrConfig) {
		t.Fatal("remote plaintext accepted")
	}
	for _, tc := range []struct {
		name string
		code int
		body string
		want error
	}{
		{"auth", 401, `secret`, onecodata.ErrAuth},
		{"forbidden", 403, `secret`, onecodata.ErrAuth},
		{"rate", 429, `secret`, onecodata.ErrUpstream},
		{"server", 500, `secret`, onecodata.ErrUpstream},
		{"malformed", 200, `{"value":{}}`, onecodata.ErrUpstream},
		{"redirect", 200, `{"value":[],"@odata.nextLink":"https://other.example/steal"}`, onecodata.ErrUpstream},
	} {
		t.Run(tc.name, func(t *testing.T) {
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				w.WriteHeader(tc.code)
				fmt.Fprint(w, tc.body)
			}))
			defer srv.Close()
			cfg.BaseURL = srv.URL + "/odata/"
			_, err := (onecodata.Client{}).FetchPlans(context.Background(), cfg)
			if !errors.Is(err, tc.want) || strings.Contains(err.Error(), "secret") {
				t.Fatalf("error: %v", err)
			}
		})
	}
	data, _ := json.Marshal(cfg)
	if strings.Contains(string(data), "secret") {
		t.Fatal("secret in config")
	}
}
