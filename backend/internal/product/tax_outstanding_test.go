package product

import "testing"

func TestTaxOutstandingPreservesReceiptsAndExactKopecks(t *testing.T) {
	parts := func(total int64, hash string) []Doc {
		result := []Doc{}
		for i := 0; i < 3; i++ {
			result = append(result, Doc{"external_id": "vat", "part": i, "amount": float64(total) / 300, "upstream_amount_kopecks": total, "upstream_hash": hash, "status": "expected"})
		}
		return result
	}
	previous := parts(10001, "old")
	previous[0]["amount"], previous[0]["status"] = 33.34, "received"
	previous[1]["amount"], previous[2]["amount"] = 33.34, 33.33
	updated := parts(6667, "new")
	if err := rebalanceTaxOutstanding(updated, previous); err != nil {
		t.Fatal(err)
	}
	if !flag(updated[0], "preserve_receipt") || number(updated[1], "amount") != 33.34 || number(updated[2], "amount") != 33.33 {
		t.Fatal("outstanding must be shared only by two unpaid parts", updated)
	}
	// Accounting receipts without a bank operation are immutable too. Once two
	// installments are paid, even a one-kopeck correction has one unpaid target.
	previous[1]["status"] = "received"
	updated = parts(1, "correction")
	if err := rebalanceTaxOutstanding(updated, previous); err != nil {
		t.Fatal(err)
	}
	if !flag(updated[0], "preserve_receipt") || !flag(updated[1], "preserve_receipt") || number(updated[2], "amount") != .01 {
		t.Fatal("kopeck correction changed paid history", updated)
	}
	previous[2]["status"] = "received"
	if err := rebalanceTaxOutstanding(parts(500, "new-debt"), previous); err == nil {
		t.Fatal("new debt on a fully paid schedule must require a new obligation")
	}
}

func TestUnchangedTaxSnapshotDoesNotResurrectPaidDebt(t *testing.T) {
	previous := []Doc{
		{"external_id": "vat", "part": 0, "amount": 33.34, "status": "received", "upstream_hash": "original", "last_seen_upstream_hash": "latest"},
		{"external_id": "vat", "part": 1, "amount": 33.34, "status": "received", "upstream_hash": "latest", "last_seen_upstream_hash": "latest"},
		{"external_id": "vat", "part": 2, "amount": 33.33, "status": "expected", "upstream_hash": "latest", "last_seen_upstream_hash": "latest"},
	}
	incoming := []Doc{}
	for i := 0; i < 3; i++ {
		incoming = append(incoming, Doc{"external_id": "vat", "part": i, "amount": 22.22, "status": "expected", "upstream_hash": "latest", "upstream_amount_kopecks": int64(6667)})
	}
	if err := rebalanceTaxOutstanding(incoming, previous); err != nil {
		t.Fatal(err)
	}
	if number(incoming[2], "amount") != 33.33 || !flag(incoming[0], "preserve_receipt") || !flag(incoming[1], "preserve_receipt") {
		t.Fatal("unchanged outstanding was redistributed after payment", incoming)
	}
}
