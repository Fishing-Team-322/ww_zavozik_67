package main

import (
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"testing"
)

func TestInternalMembershipChangesSignedBusinessFlow(t *testing.T) {
	ops := []domain.Operation{
		{Category: domain.CatOther, Direction: domain.Out, Amount: 100},
		{Category: domain.CatOwnerLoan, Direction: domain.In, Amount: 200},
		{Category: domain.CatSupplier, Direction: domain.Out, Amount: 50},
		{Category: domain.CatOwnerLoan, Direction: domain.In, Amount: 300},
	}
	labels := []categorize.Result{{Category: domain.CatOwnTransfer}, {Category: domain.CatRevenueB2B},
		{Category: domain.CatServices}, {Category: domain.CatOwnTransfer}}
	r, err := compare(ops, labels)
	if err != nil {
		t.Fatal(err)
	}
	if r.Changed != 4 || r.InternalChanged != 2 || r.BusinessNetDelta != 300 || r.InternalTurnover != 300 {
		t.Fatalf("incorrect flow membership impact: %+v", r)
	}
	if r.ChangedTurnover != 650 {
		t.Fatalf("turnover: %v", r.ChangedTurnover)
	}
	if _, err := compare(ops, labels[:2]); err == nil {
		t.Fatal("accepted missing labels")
	}
}
