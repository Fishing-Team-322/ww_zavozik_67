package casecsv

import (
	"context"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

const sample = "\uFEFFcompany_id;operation_id;operation_date;amount;direction;counterparty_inn;counterparty_name;payment_purpose;balance_eod\n" +
	"C001;C001-000001;2024-10-01;990.00;Списание;0068275202;ПАО «Банк»;Комиссия за ведение счета;1244821.98\n" +
	"C001;C001-000002;2024-10-02;170892.06;Поступление;;ООО «Элеватор-242»;\"Оплата; по УПД\";1527714.04\n"

func TestParse(t *testing.T) {
	b, err := Parser{}.Parse(context.Background(), "", strings.NewReader(sample))
	if err != nil {
		t.Fatal(err)
	}
	if len(b.Operations) != 2 {
		t.Fatalf("got %d ops", len(b.Operations))
	}
	op := b.Operations[1]
	if op.Direction != domain.In || op.Amount != 170892.06 || op.CounterpartyINN != "" ||
		op.Purpose != "Оплата; по УПД" || *op.BalanceEOD != 1527714.04 {
		t.Errorf("bad op: %+v", op)
	}
	if b.Operations[0].CounterpartyINN != "0068275202" {
		t.Error("leading zeros in INN lost")
	}
}

func TestDetect(t *testing.T) {
	if !(Parser{}).Detect("C001.csv", []byte(sample)) {
		t.Error("should detect case csv")
	}
	if (Parser{}).Detect("x.csv", []byte("date,amount\n")) {
		t.Error("should not detect foreign csv")
	}
}
