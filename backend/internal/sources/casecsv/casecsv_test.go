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

func row(amount, direction, balance string) string {
	return "\uFEFF" + strings.Join(header, ";") + "\n" +
		"C001;C001-000001;2024-10-01;" + amount + ";" + direction + ";0068275202;ПАО «Банк»;Комиссия;" + balance + "\n"
}

// Малформед-суммы и остатки дают диагностику с полем и строкой, но не
// цитируют исходную ячейку: суммы не должны попадать в логи.
func TestParseRejectsInvalidNumbersWithoutEchoingCell(t *testing.T) {
	const (
		secretAmount  = "123456.78 RUB"
		secretBalance = "987654.32 RUB"
	)
	tests := []struct {
		name      string
		amount    string
		direction string
		balance   string
		want      string
	}{
		{"amount not a number", secretAmount, "Списание", "1", "line 2: amount: not a number"},
		{"amount out of range", "1e400", "Списание", "1", "line 2: amount: out of range"},
		{"amount NaN", "NaN", "Списание", "1", "line 2: amount: must be finite"},
		{"amount +Inf", "+Inf", "Поступление", "1", "line 2: amount: must be finite"},
		{"amount negative", "-10", "Поступление", "1", "line 2: amount: must be non-negative"},
		{"balance not a number", "10", "Списание", secretBalance, "line 2: balance_eod: not a number"},
		{"balance NaN", "10", "Списание", "NaN", "line 2: balance_eod: must be finite"},
		{"balance -Inf", "10", "Списание", "-Inf", "line 2: balance_eod: must be finite"},
		{"unknown direction", "10", "Перевод", "1", "line 2: direction: want"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			_, err := Parser{}.Parse(context.Background(), "", strings.NewReader(row(tt.amount, tt.direction, tt.balance)))
			if err == nil {
				t.Fatal("want error")
			}
			if !strings.Contains(err.Error(), tt.want) {
				t.Errorf("error %q does not mention %q", err, tt.want)
			}
			for _, secret := range []string{secretAmount, secretBalance, "Перевод"} {
				if strings.Contains(err.Error(), secret) {
					t.Errorf("error leaks input %q: %v", secret, err)
				}
			}
		})
	}
}

func TestParseAcceptsZeroAndNegativeBalance(t *testing.T) {
	tests := []struct {
		name    string
		amount  string
		balance string
		wantAmt domain.Money
		wantBal domain.Money
	}{
		{"zero amount", "0", "0", 0, 0},
		{"positive amount", "170892.06", "-152.5", 170892.06, -152.5},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b, err := Parser{}.Parse(context.Background(), "", strings.NewReader(row(tt.amount, "Списание", tt.balance)))
			if err != nil {
				t.Fatal(err)
			}
			op := b.Operations[0]
			if op.Amount != tt.wantAmt || op.BalanceEOD == nil || *op.BalanceEOD != tt.wantBal {
				t.Errorf("got amount %v balance %v", op.Amount, op.BalanceEOD)
			}
		})
	}
}
