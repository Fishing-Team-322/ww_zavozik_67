package demo

import "testing"

func TestFixtureForecastAndNoDoubleCount(t *testing.T) {
	c := Build()
	if c.Before.ClosingKopecks != 25000000 || c.After.ClosingKopecks != 25000000 {
		t.Fatalf("close: %+v", c)
	}
	if c.After.Balances[2].BalanceKopecks != 0 || c.After.Events[3].AmountKopecks != 25000000 || c.After.Events[3].Version != 2 {
		t.Fatalf("partial payment scenario: %+v", c.After)
	}
	var client int64
	for _, e := range c.After.Events {
		if e.ExternalID == "invoice-client" || e.ExternalID == "payment-client-1" {
			client += e.AmountKopecks
		}
		if e.DataMode != "fixture" {
			t.Fatal("fixture mislabeled")
		}
	}
	if client != 35000000 {
		t.Fatalf("double count or lost payment: %d", client)
	}
}
