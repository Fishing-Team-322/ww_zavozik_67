package main

import (
	"bytes"
	"context"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// Метки должны совпадать с прямым вызовом categorize.DefaultRules.
func TestRunMatchesRules(t *testing.T) {
	in := "\xef\xbb\xbfid;direction;counterparty_inn;counterparty_name;payment_purpose\n" +
		"a;Списание;0071000001;Казначейство России (ФНС России);ЕНП\n" +
		"b;out;;ПАО «Банк»;Комиссия за ведение счета\n" +
		"c;Поступление;;ПАО «Банк»;\"Зачисление; по СБП\"\n" +
		"d;in;;Кто-то;\n"
	var out bytes.Buffer
	if err := run(context.Background(), strings.NewReader(in), &out); err != nil {
		t.Fatal(err)
	}
	ops := []domain.Operation{
		{Direction: domain.Out, CounterpartyName: "Казначейство России (ФНС России)", Purpose: "ЕНП"},
		{Direction: domain.Out, CounterpartyName: "ПАО «Банк»", Purpose: "Комиссия за ведение счета"},
		{Direction: domain.In, CounterpartyName: "ПАО «Банк»", Purpose: "Зачисление; по СБП"},
		{Direction: domain.In, CounterpartyName: "Кто-то"},
	}
	res, _ := categorize.Chain{Steps: []categorize.Categorizer{categorize.DefaultRules}, Threshold: 0.5}.Categorize(context.Background(), ops)
	want := "id;category;confidence\n"
	for i, id := range []string{"a", "b", "c", "d"} {
		conf := "0.90"
		if res[i].Confidence == 0 {
			conf = "0.00"
		}
		want += id + ";" + string(res[i].Category) + ";" + conf + "\n"
	}
	if out.String() != want {
		t.Errorf("got\n%s\nwant\n%s", out.String(), want)
	}
	if !strings.Contains(want, "d;other;0.00") {
		t.Errorf("rules must give other for unknown: %s", want)
	}
}

func TestRunBadInput(t *testing.T) {
	var out bytes.Buffer
	if err := run(context.Background(), strings.NewReader("id;purpose\n1;x\n"), &out); err == nil {
		t.Error("missing columns must fail")
	}
	if err := run(context.Background(), strings.NewReader("direction;counterparty_name;payment_purpose\nвбок;a;b\n"), &out); err == nil {
		t.Error("bad direction must fail")
	}
}
