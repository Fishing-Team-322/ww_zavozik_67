package onecbank

import (
	"bytes"
	"context"
	"errors"
	"os"
	"strings"
	"testing"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
)

var demo = contracts.Identity{CompanyID: "demo-company", CompanyINN: "7700000000", CompanyAccount: "40702810000000000001"}

func fixture(t *testing.T, name string) []byte {
	t.Helper()
	b, err := os.ReadFile("../../../testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

func TestFixtures(t *testing.T) {
	for _, tc := range []struct {
		name   string
		prefix []byte
	}{
		{"onec_bank_utf8.txt", nil}, {"onec_bank_cp1251.txt", nil}, {"onec_bank_utf8.txt", []byte{0xef, 0xbb, 0xbf}},
	} {
		t.Run(tc.name+string(tc.prefix), func(t *testing.T) {
			data := append(tc.prefix, fixture(t, tc.name)...)
			batch, err := (Parser{}).Parse(context.Background(), bytes.NewReader(data), demo)
			if err != nil {
				t.Fatal(err)
			}
			if batch.Stats.Parsed != 4 || batch.Stats.Accepted != 2 || batch.Stats.Duplicates != 1 || batch.Stats.Rejected != 1 {
				t.Fatalf("stats: %+v", batch.Stats)
			}
			if len(batch.Operations) != 2 || batch.Operations[0].Direction != "out" || batch.Operations[1].Direction != "in" {
				t.Fatalf("operations: %+v", batch.Operations)
			}
			if batch.Operations[0].AmountKopecks != 100005 || batch.Operations[1].AmountKopecks != 100005 {
				t.Fatal("decimal amounts")
			}
			if batch.Operations[0].Date != "2026-10-23" || !batch.Operations[0].Executed {
				t.Fatal("execution date")
			}
			if batch.Operations[0].BalanceEODKopecks == nil || *batch.Operations[0].BalanceEODKopecks != 1000000 {
				t.Fatal("balance")
			}
			if batch.Operations[0].Purpose != "Оплата синтетических услуг" {
				t.Fatal("purpose")
			}
			if batch.Issues[0].Code != "not_executed" {
				t.Fatal("unexecuted document")
			}
		})
	}
}

func TestCP1251IsEncoded(t *testing.T) {
	data := fixture(t, "onec_bank_cp1251.txt")
	if bytes.Contains(data, []byte("СекцияДокумент")) {
		t.Fatal("fixture appears to be UTF-8")
	}
}

func TestMoney(t *testing.T) {
	for _, s := range []string{"1000,05", "1000.05"} {
		n, e := parseMoney(s)
		if e != nil || n != 100005 {
			t.Fatalf("%s: %d %v", s, n, e)
		}
	}
	for _, s := range []string{"", "-1", "+1", "1e3", "NaN", "1.234", "92233720368547759", "1,2,3"} {
		if _, e := parseMoney(s); e == nil {
			t.Fatalf("accepted %q", s)
		}
	}
}

func TestRejectedDocuments(t *testing.T) {
	base := string(fixture(t, "onec_bank_utf8.txt"))
	for _, tc := range []struct{ old, new, code string }{
		{"Сумма=1000,05", "Сумма=NaN", "invalid_amount"},
		{"Номер=  001  ", "Номер=", "missing_document_number"},
		{"Дата=22.10.2026", "Дата=31.02.2026", "invalid_document_date"},
		{"ДатаСписано=23.10.2026", "ДатаСписано=31.02.2026", "invalid_execution_date"},
		{"ПлательщикСчет=40702810000000000001", "ПлательщикСчет=40702810000000000003", "unknown_account"},
		{"ПлательщикИНН=7700000000", "ПлательщикИНН=7700000001", "inn_mismatch"},
	} {
		t.Run(tc.code, func(t *testing.T) {
			data := strings.Replace(base, tc.old, tc.new, 1)
			b, e := (Parser{}).Parse(context.Background(), strings.NewReader(data), demo)
			if e != nil {
				t.Fatal(e)
			}
			if len(b.Issues) == 0 || b.Issues[0].Code != tc.code {
				t.Fatalf("issues: %+v", b.Issues)
			}
		})
	}
}

func TestInvalidFormatAndLimits(t *testing.T) {
	base := fixture(t, "onec_bank_utf8.txt")
	for _, data := range [][]byte{nil, []byte("not 1C\n"), bytes.Replace(base, []byte("КонецФайла"), []byte(""), 1), bytes.Repeat([]byte("x"), MaxFileBytes+1)} {
		_, err := (Parser{}).Parse(context.Background(), bytes.NewReader(data), demo)
		if err == nil {
			t.Fatal("invalid input accepted")
		}
	}
	_, err := (Parser{}).Parse(context.Background(), bytes.NewReader(bytes.Repeat([]byte("x"), MaxFileBytes+1)), demo)
	if !errors.Is(err, ErrTooLarge) {
		t.Fatal(err)
	}
	longLine := append([]byte("1CClientBankExchange\nKey="), bytes.Repeat([]byte("x"), MaxLineBytes)...)
	_, err = (Parser{}).Parse(context.Background(), bytes.NewReader(longLine), demo)
	if !errors.Is(err, ErrTooLarge) {
		t.Fatal(err)
	}
	for _, data := range [][]byte{
		[]byte("1CClientBankExchange\nКодировка=DOS\nКонецФайла\n"),
		[]byte("1CClientBankExchange\nКлюч=bad\x00value\nКонецФайла\n"),
		append([]byte{0xef, 0xbb, 0xbf}, []byte("1CClientBankExchange\nКлюч=\xff\nКонецФайла\n")...),
		append([]byte("1CClientBankExchange\nКлюч="), append([]byte{0x98}, []byte("\nКонецФайла\n")...)...),
	} {
		if _, err := (Parser{}).Parse(context.Background(), bytes.NewReader(data), demo); !errors.Is(err, ErrInvalid) {
			t.Fatalf("invalid encoding/content: %v", err)
		}
	}
	var many strings.Builder
	many.WriteString("1CClientBankExchange\n")
	for range MaxDocuments + 1 {
		many.WriteString("СекцияДокумент=x\nКонецДокумента\n")
	}
	many.WriteString("КонецФайла\n")
	if _, err := (Parser{}).Parse(context.Background(), strings.NewReader(many.String()), demo); !errors.Is(err, ErrTooLarge) {
		t.Fatalf("document limit: %v", err)
	}
}

func TestUnknownCompanySide(t *testing.T) {
	id := demo
	id.CompanyAccount = "40702810000000000002"
	id.CompanyINN = "7500000000"
	b, err := (Parser{}).Parse(context.Background(), bytes.NewReader(fixture(t, "onec_bank_utf8.txt")), id)
	if err != nil {
		t.Fatal(err)
	}
	if b.Stats.Accepted != 0 || b.Stats.Rejected != 4 {
		t.Fatalf("stats: %+v", b.Stats)
	}
}

func TestINNFallbackWhenAccountMissing(t *testing.T) {
	data := string(fixture(t, "onec_bank_utf8.txt"))
	data = strings.Replace(data, "ПлательщикСчет=40702810000000000001\nПлательщикИНН", "ПлательщикСчет=\nПлательщикИНН", 1)
	batch, err := (Parser{}).Parse(context.Background(), strings.NewReader(data), demo)
	if err != nil {
		t.Fatal(err)
	}
	if batch.Stats.Accepted != 2 || batch.Operations[0].Direction != "out" {
		t.Fatalf("INN fallback: %+v", batch.Stats)
	}
}

func FuzzParserNoPanic(f *testing.F) {
	seed, err := os.ReadFile("../../../testdata/onec_bank_utf8.txt")
	if err != nil {
		f.Fatal(err)
	}
	f.Add(seed)
	f.Add([]byte("1CClientBankExchange\nКонецФайла\n"))
	f.Fuzz(func(t *testing.T, data []byte) {
		if len(data) > 65536 {
			t.Skip()
		}
		_, _ = (Parser{}).Parse(context.Background(), bytes.NewReader(data), demo)
	})
}
