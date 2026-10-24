// Package sources — адаптеры источников данных. Владелец: Бэк 1.
//
// Два вида адаптеров:
//   - Parser — разбирает загруженный файл (выписка 1CClientBankExchange,
//     Excel, CSV);
//   - Puller — сам ходит во внешнюю систему (Google Sheets, 1С OData, ФНС).
//
// Оба отдают Batch: факт (операции) и план (ожидаемые события). Каждая
// запись помечена Source — пользователь видит, откуда она.
//
// Новый источник = новый тип + регистрация в init():
//
//	func init() { sources.Parsers.Register("onec_bank_file", OneCParser{}) }
//
// TODO(Бэк 1): onec_bank_file, excel, fns, проверка контрагента.
// TODO(Бэк 2): gsheets (плановые платежи).
// TODO(Бэк 3): onec_odata, если поднимется база.
package sources

import (
	"context"
	"io"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/registry"
)

type Batch struct {
	Company    *domain.Company // если источник знает реквизиты владельца счёта
	Operations []domain.Operation
	Planned    []domain.PlannedEvent
}

type Parser interface {
	Kind() domain.SourceKind
	// Detect — похож ли файл на этот формат (по имени и первым байтам).
	Detect(filename string, head []byte) bool
	Parse(ctx context.Context, companyID string, r io.Reader) (Batch, error)
}

type Puller interface {
	Kind() domain.SourceKind
	Fetch(ctx context.Context, c domain.Company, cfg map[string]any, since *time.Time) (Batch, error)
}

var (
	Parsers = registry.New[Parser]()
	Pullers = registry.New[Puller]()
)

// DetectParser выбирает парсер для загруженного файла.
func DetectParser(filename string, head []byte) (Parser, bool) {
	for _, name := range Parsers.Names() {
		p, _ := Parsers.Get(name)
		if p.Detect(filename, head) {
			return p, true
		}
	}
	return nil, false
}
