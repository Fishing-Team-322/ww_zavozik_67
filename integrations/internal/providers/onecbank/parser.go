package onecbank

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/money"
)

const MaxFileBytes = 4 << 20
const MaxLineBytes = 16 << 10
const MaxDocuments = 10000

var ErrTooLarge = errors.New("file or line exceeds limit")
var ErrInvalid = errors.New("invalid 1CClientBankExchange file")

type Parser struct{}

func (Parser) Kind() string { return contracts.SourceKind }

func (Parser) Parse(ctx context.Context, r io.Reader, identity contracts.Identity) (contracts.ImportBatch, error) {
	batch := contracts.NewBatch(identity.CompanyID)
	if err := identity.Validate(); err != nil {
		return batch, err
	}
	data, err := io.ReadAll(io.LimitReader(r, MaxFileBytes+1))
	if err != nil {
		return batch, ErrInvalid
	}
	if len(data) > MaxFileBytes {
		return batch, ErrTooLarge
	}
	if len(data) == 0 {
		return batch, ErrInvalid
	}
	decoded, err := decode(data)
	if err != nil {
		return batch, err
	}
	scanner := bufio.NewScanner(strings.NewReader(decoded))
	scanner.Buffer(make([]byte, 4096), MaxLineBytes)
	section := ""
	fields := map[string]string{}
	balances := make(map[string]map[string]int64)
	seen := make(map[string]bool)
	fileStarted, fileEnded := false, false
	sectionIndex := 0
	for scanner.Scan() {
		if err := ctx.Err(); err != nil {
			return batch, err
		}
		line := strings.TrimSpace(scanner.Text())
		if strings.ContainsRune(line, '\x00') {
			return batch, ErrInvalid
		}
		if line == "" {
			continue
		}
		if !fileStarted {
			if strings.TrimPrefix(line, "\ufeff") != "1CClientBankExchange" {
				return batch, ErrInvalid
			}
			fileStarted = true
			continue
		}
		if fileEnded {
			return batch, ErrInvalid
		}
		switch {
		case line == "СекцияРасчСчет":
			if section != "" {
				return batch, ErrInvalid
			}
			section = "account"
			fields = map[string]string{}
		case strings.HasPrefix(line, "СекцияДокумент="):
			if section != "" {
				return batch, ErrInvalid
			}
			if batch.Stats.Parsed >= MaxDocuments {
				return batch, ErrTooLarge
			}
			section = "document"
			fields = map[string]string{}
			sectionIndex++
			batch.Stats.Parsed++
		case line == "КонецРасчСчет":
			if section != "account" {
				return batch, ErrInvalid
			}
			if account := normAccount(fields["РасчСчет"]); account != "" {
				start, es := parseDate(fields["ДатаНачала"])
				end, ee := parseDate(fields["ДатаКонца"])
				balance, eb := parseMoney(fields["КонечныйОстаток"])
				if es == nil && ee == nil && eb == nil && start == end {
					if balances[account] == nil {
						balances[account] = map[string]int64{}
					}
					balances[account][end] = balance
				}
			}
			section = ""
			fields = map[string]string{}
		case line == "КонецДокумента":
			if section != "document" {
				return batch, ErrInvalid
			}
			op, code := parseDocument(fields, identity)
			if code != "" {
				batch.Stats.Rejected++
				batch.Issues = append(batch.Issues, contracts.Issue{Code: code, Section: sectionIndex, Message: issueMessage(code)})
			} else if seen[op.DedupKey] {
				batch.Stats.Duplicates++
			} else {
				seen[op.DedupKey] = true
				batch.Operations = append(batch.Operations, op)
				batch.Stats.Accepted++
			}
			section = ""
			fields = map[string]string{}
		case line == "КонецФайла":
			if section != "" {
				return batch, ErrInvalid
			}
			fileEnded = true
		default:
			key, value, ok := strings.Cut(line, "=")
			if !ok || strings.TrimSpace(key) == "" {
				return batch, ErrInvalid
			}
			key = strings.TrimSpace(key)
			if section != "" {
				fields[key] = strings.TrimSpace(value)
			}
			if section == "" && key == "Кодировка" && strings.EqualFold(strings.TrimSpace(value), "DOS") {
				return batch, ErrInvalid
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return batch, ErrTooLarge
	}
	if !fileStarted || !fileEnded {
		return batch, ErrInvalid
	}
	for j := range batch.Operations {
		op := &batch.Operations[j]
		if byDate := balances[op.Account]; byDate != nil {
			if value, ok := byDate[op.Date]; ok {
				op.BalanceEODKopecks = &value
			}
		}
	}
	return batch, nil
}

func parseDocument(f map[string]string, id contracts.Identity) (contracts.Operation, string) {
	var op contracts.Operation
	if normText(f["Номер"]) == "" {
		return op, "missing_document_number"
	}
	amount, err := parseMoney(f["Сумма"])
	if err != nil {
		return op, "invalid_amount"
	}
	if _, err := parseDate(f["Дата"]); err != nil {
		return op, "invalid_document_date"
	}
	payerAccount, recipientAccount := normAccount(f["ПлательщикСчет"]), normAccount(f["ПолучательСчет"])
	payerINN, recipientINN := normDigits(f["ПлательщикИНН"]), normDigits(f["ПолучательИНН"])
	payerMatch := payerAccount == id.CompanyAccount
	recipientMatch := recipientAccount == id.CompanyAccount
	if payerMatch && recipientMatch {
		return op, "ambiguous_direction"
	}
	if !payerMatch && !recipientMatch {
		if payerAccount != "" && recipientAccount != "" {
			return op, "unknown_account"
		}
		payerMatch = payerINN == id.CompanyINN
		recipientMatch = recipientINN == id.CompanyINN
		if payerMatch == recipientMatch {
			return op, "unknown_direction"
		}
	}
	var executionField string
	if payerMatch {
		if payerINN != "" && payerINN != id.CompanyINN {
			return op, "inn_mismatch"
		}
		if recipientINN == id.CompanyINN {
			return op, "ambiguous_direction"
		}
		op.Direction = "out"
		executionField = f["ДатаСписано"]
		if payerAccount == "" {
			payerAccount = id.CompanyAccount
		}
	} else {
		if recipientINN != "" && recipientINN != id.CompanyINN {
			return op, "inn_mismatch"
		}
		if payerINN == id.CompanyINN {
			return op, "ambiguous_direction"
		}
		op.Direction = "in"
		executionField = f["ДатаПоступило"]
		if recipientAccount == "" {
			recipientAccount = id.CompanyAccount
		}
	}
	if strings.TrimSpace(executionField) == "" {
		return op, "not_executed"
	}
	date, err := parseDate(executionField)
	if err != nil {
		return op, "invalid_execution_date"
	}
	op.Date, op.AmountKopecks, op.SourceKind, op.Executed = date, amount, contracts.SourceKind, true
	op.Account = id.CompanyAccount
	if op.Direction == "out" {
		op.CounterpartyINN = recipientINN
		op.CounterpartyName = firstNonEmpty(f["Получатель1"], f["Получатель"])
	} else {
		op.CounterpartyINN = payerINN
		op.CounterpartyName = firstNonEmpty(f["Плательщик1"], f["Плательщик"])
	}
	op.Purpose = f["НазначениеПлатежа"]
	if op.Purpose == "" {
		parts := []string{}
		for j := 1; j <= 6; j++ {
			if s := f["НазначениеПлатежа"+strconv.Itoa(j)]; s != "" {
				parts = append(parts, s)
			}
		}
		op.Purpose = strings.Join(parts, " ")
	}
	op.CounterpartyName = normText(op.CounterpartyName)
	op.Purpose = normText(op.Purpose)
	documentDate, _ := parseDate(f["Дата"])
	keyParts := []string{id.CompanyAccount, op.Direction, date, documentDate, normText(f["Номер"]), strconv.FormatInt(amount, 10), payerAccount, recipientAccount, payerINN, recipientINN, normText(op.CounterpartyName), normText(op.Purpose)}
	sum := sha256.Sum256([]byte(strings.ToLower(strings.Join(keyParts, "\x00"))))
	op.DedupKey = hex.EncodeToString(sum[:])
	return op, ""
}

func parseDate(s string) (string, error) {
	t, err := time.Parse("02.01.2006", strings.TrimSpace(s))
	if err != nil {
		return "", ErrInvalid
	}
	return t.Format("2006-01-02"), nil
}

func parseMoney(s string) (int64, error) {
	return money.Parse(s)
}

func normText(s string) string    { return strings.Join(strings.Fields(s), " ") }
func normDigits(s string) string  { return strings.Join(strings.Fields(s), "") }
func normAccount(s string) string { return normDigits(s) }
func firstNonEmpty(a, b string) string {
	if a != "" {
		return a
	}
	return b
}

func issueMessage(code string) string {
	switch code {
	case "invalid_amount":
		return "Payment amount is invalid"
	case "missing_document_number":
		return "Document number is missing"
	case "invalid_document_date":
		return "Document date is invalid"
	case "invalid_execution_date":
		return "Execution date is invalid"
	case "not_executed":
		return "Document has no execution date"
	case "unknown_account", "unknown_direction", "ambiguous_direction", "inn_mismatch":
		return "Company side cannot be determined safely"
	default:
		return "Document was rejected"
	}
}

func decode(data []byte) (string, error) {
	hasBOM := bytes.HasPrefix(data, []byte{0xef, 0xbb, 0xbf})
	data = bytes.TrimPrefix(data, []byte{0xef, 0xbb, 0xbf})
	if hasBOM {
		if !utf8.Valid(data) {
			return "", ErrInvalid
		}
		return string(data), nil
	}
	if utf8.Valid(data) {
		// A declared Windows code page wins over an accidental valid UTF-8 byte sequence.
		cp, err := decodeCP1251(data)
		if err == nil && strings.Contains(cp, "Кодировка=Windows") && !strings.Contains(string(data), "Кодировка=UTF-8") {
			return cp, nil
		}
		return string(data), nil
	}
	return decodeCP1251(data)
}

func decodeCP1251(data []byte) (string, error) {
	var b strings.Builder
	b.Grow(len(data) * 2)
	for _, c := range data {
		if c == 0x98 {
			return "", ErrInvalid
		}
		if c < 0x80 {
			b.WriteByte(c)
		} else if c >= 0xc0 {
			b.WriteRune(rune(0x0410 + int(c) - 0xc0))
		} else {
			b.WriteRune(cp1251High[c-0x80])
		}
	}
	return b.String(), nil
}

var cp1251High = [64]rune{
	0x0402, 0x0403, 0x201a, 0x0453, 0x201e, 0x2026, 0x2020, 0x2021, 0x20ac, 0x2030, 0x0409, 0x2039, 0x040a, 0x040c, 0x040b, 0x040f,
	0x0452, 0x2018, 0x2019, 0x201c, 0x201d, 0x2022, 0x2013, 0x2014, 0xfffd, 0x2122, 0x0459, 0x203a, 0x045a, 0x045c, 0x045b, 0x045f,
	0x00a0, 0x040e, 0x045e, 0x0408, 0x00a4, 0x0490, 0x00a6, 0x00a7, 0x0401, 0x00a9, 0x0404, 0x00ab, 0x00ac, 0x00ad, 0x00ae, 0x0407,
	0x00b0, 0x00b1, 0x0406, 0x0456, 0x0491, 0x00b5, 0x00b6, 0x00b7, 0x0451, 0x2116, 0x0454, 0x00bb, 0x0458, 0x0405, 0x0455, 0x0457,
}
