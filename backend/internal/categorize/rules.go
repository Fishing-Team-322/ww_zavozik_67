package categorize

import (
	"context"
	"regexp"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
)

// Rule срабатывает, если подходит направление (пусто — любое) и регулярка
// находится в назначении или в названии контрагента.
type Rule struct {
	Category  domain.Category
	Direction domain.Direction
	Purpose   *regexp.Regexp
	Name      *regexp.Regexp
}

func (r Rule) match(op domain.Operation, purpose, name string) bool {
	if r.Direction != "" && r.Direction != op.Direction {
		return false
	}
	return (r.Purpose != nil && r.Purpose.MatchString(purpose)) ||
		(r.Name != nil && r.Name.MatchString(name))
}

// Rules — первое совпавшее правило побеждает, порядок важен.
type Rules []Rule

func re(s string) *regexp.Regexp { return regexp.MustCompile("(?i)" + s) }

// DefaultRules — стартовый набор по шаблонам из датасета кейса.
var DefaultRules = Rules{
	{Category: domain.CatOwnerLoan, Purpose: re(`за[еёий]м.*учредител|учредител.*за[еёий]м`)},
	{Category: domain.CatOwnTransfer, Purpose: re(`собственн\S* средств`)},
	{Category: domain.CatEnforcement, Purpose: re(`исполнительн\S* лист|инкассов\S* поручен`)},
	{Category: domain.CatRefund, Purpose: re(`^возврат`)},
	{Category: domain.CatTax, Direction: domain.Out, Purpose: re(`(^|[^\p{L}])ЕНП([^\p{L}]|$)|единый налоговый`), Name: re(`казначейство`)},
	{Category: domain.CatSalary, Direction: domain.Out, Purpose: re(`заработн\S* плат`)},
	{Category: domain.CatLoanPayment, Direction: domain.Out, Purpose: re(`погашение кредита|процент\S* за пользование`)},
	{Category: domain.CatLeasing, Direction: domain.Out, Purpose: re(`лизинг`)},
	{Category: domain.CatRent, Direction: domain.Out, Purpose: re(`аренд`)},
	{Category: domain.CatBankFee, Direction: domain.Out, Purpose: re(`комисси`)},
	{Category: domain.CatUtilities, Direction: domain.Out, Purpose: re(`электроэнерги|водоснабжен|теплоснабжен|вывоз тко|связи`)},
	{Category: domain.CatMarketing, Direction: domain.Out, Purpose: re(`рекламн`)},
	{Category: domain.CatRevenueAcquiring, Direction: domain.In, Purpose: re(`эквайринг`)},
	{Category: domain.CatRevenueSBP, Direction: domain.In, Purpose: re(`(^|[^\p{L}])СБП([^\p{L}]|$)`)},
	{Category: domain.CatRevenueCash, Direction: domain.In, Purpose: re(`взнос наличных|инкассированн`)},
	{Category: domain.CatRevenueMarketplace, Direction: domain.In, Name: re(`маркетплейс`)},
	{Category: domain.CatRevenueB2B, Direction: domain.In, Purpose: re(`оплата|предоплата|доплата|расчет`)},
	{Category: domain.CatSupplier, Direction: domain.Out, Purpose: re(`упд|за товар|поставк|продукци`)},
	{Category: domain.CatServices, Direction: domain.Out, Purpose: re(`услуг`)},
}

var ownerName = re(`учредител|собственник`)
var ownerLoanPurpose = re(`за[еёий]м`)

func (rs Rules) Categorize(_ context.Context, ops []domain.Operation) ([]Result, error) {
	out := make([]Result, len(ops))
	for i, op := range ops {
		purpose := strings.TrimSpace(string(op.Purpose))
		name := string(op.CounterpartyName)
		// The counterparty identifies the lender even when the purpose only says
		// «предоставление беспроцентного займа». Do not classify arbitrary
		// payments to the owner as financing.
		if ownerName.MatchString(name) && ownerLoanPurpose.MatchString(purpose) {
			out[i] = Result{Category: domain.CatOwnerLoan, Confidence: 0.9, Method: domain.MethodRule}
			continue
		}
		for _, r := range rs {
			if r.match(op, purpose, name) {
				out[i] = Result{Category: r.Category, Confidence: 0.9, Method: domain.MethodRule}
				break
			}
		}
	}
	return out, nil
}
