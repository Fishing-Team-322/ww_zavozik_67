package domain

import (
	"bytes"
	"log/slog"
	"strings"
	"testing"
	"time"
)

func TestSensitiveValuesAreRedactedInLogs(t *testing.T) {
	var buf bytes.Buffer
	log := slog.New(slog.NewJSONHandler(&buf, nil))

	bal := Money(1527714.04)
	op := Operation{
		ID:               "C001-000002",
		CompanyID:        "C001",
		Date:             time.Date(2024, 10, 2, 0, 0, 0, 0, time.UTC),
		Amount:           170892.06,
		Direction:        In,
		CounterpartyINN:  "0048401219",
		CounterpartyName: "ООО «Элеватор-242»",
		Purpose:          "Оплата по УПД № 279 от 19.08.2024",
		BalanceEOD:       &bal,
	}
	log.Info("op", "op", op, "amount", op.Amount, "inn", op.CounterpartyINN,
		"name", op.CounterpartyName, "purpose", op.Purpose)

	out := buf.String()
	for _, secret := range []string{"170892", "0048401219", "Элеватор", "УПД", "1527714"} {
		if strings.Contains(out, secret) {
			t.Errorf("log contains %q: %s", secret, out)
		}
	}
	if !strings.Contains(out, "C001-000002") {
		t.Errorf("log lost safe operation id: %s", out)
	}
}
