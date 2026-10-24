package categorize

import (
	"context"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

func TestDefaultRules(t *testing.T) {
	cases := []struct {
		dir     domain.Direction
		name    string
		purpose string
		want    domain.Category
	}{
		{domain.Out, "Казначейство России (ФНС России)", "ЕНП", domain.CatTax},
		{domain.Out, "Казначейство России (ФНС России)", "", domain.CatTax},
		{domain.Out, "ПАО «Банк»", "Перечисление заработной платы (аванс) за декабрь 2025 г.", domain.CatSalary},
		{domain.In, "ПАО «Банк»", "Зачисление средств по операциям эквайринга. Мерчант №4010196", domain.CatRevenueAcquiring},
		{domain.In, "ПАО «Банк»", "Зачисление по операциям оплаты через СБП (QR-код)", domain.CatRevenueSBP},
		{domain.In, "Учредитель (физическое лицо)", "Предоставление беспроцентного займа учредителем по договору № 358/25", domain.CatOwnerLoan},
		{domain.Out, "Учредитель (физическое лицо)", "Возврат беспроцентного займа учредителю", domain.CatOwnerLoan},
		{domain.Out, "ООО «Модный двор-224»", "Перевод собственных средств на расчетный счет в АО «Банк-3»", domain.CatOwnTransfer},
		{domain.Out, "ООО «Истец-637»", "Списание по исполнительному листу ФС № 77567963", domain.CatEnforcement},
		{domain.Out, "ПАО «Банк»", "Погашение кредита по договору № КД-8058", domain.CatLoanPayment},
		{domain.In, "ООО «Элеватор-242»", "Оплата по УПД № 279 от 19.08.2024. НДС не облагается", domain.CatRevenueB2B},
		{domain.Out, "ООО «Мясокомбинат-1»", "Оплата по УПД № 1 от 01.01.2025 за мясную продукцию", domain.CatSupplier},
		{domain.Out, "Кто-то", "", domain.CatOther},
	}
	ops := make([]domain.Operation, len(cases))
	for i, c := range cases {
		ops[i] = domain.Operation{Direction: c.dir, CounterpartyName: domain.Name(c.name), Purpose: domain.Purpose(c.purpose)}
	}
	res, err := Chain{Steps: []Categorizer{DefaultRules}, Threshold: 0.5}.Categorize(context.Background(), ops)
	if err != nil {
		t.Fatal(err)
	}
	for i, c := range cases {
		if res[i].Category != c.want {
			t.Errorf("%q / %q: got %s, want %s", c.name, c.purpose, res[i].Category, c.want)
		}
	}
}
