package product

import (
	"regexp"
	"strconv"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// Consume the whole numeric token, including unsupported separators, so a
// malformed number can never be accepted by matching only its valid suffix.
var amountLiteral = regexp.MustCompile(`[+-]?[0-9][0-9\s\p{Zs}.,_/'’]*(?:[eE][+-]?[0-9]+)?`)
var amountUnit = regexp.MustCompile(`(?i)^(млн|миллион[а-я]*|тыс[а-я.]*|к|руб[а-я.]*|₽)(?:\s|[,.!?;:]|$)`)
var dateISO = regexp.MustCompile(`\b(20[0-9]{2}-[01][0-9]-[0-3][0-9])\b`)
var dateDay = regexp.MustCompile(`\b([0-3]?[0-9])(?:-го|\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря))(?:\s+(20[0-9]{2}))?`)
var clientName = regexp.MustCompile(`(?i)клиент\s+(.+?)\s+(?:обещал|заплатит|переведёт|переведет)`)

func (s *Service) parseEvent(b Doc) (Result, error) {
	return parseEventAt(b, today())
}

func parseEventAt(b Doc, now time.Time) (Result, error) {
	if e := fields(b, "text"); e != nil {
		return Result{}, e
	}
	phrase := text(b, "text")
	if utf8.RuneCountInString(phrase) == 0 || utf8.RuneCountInString(phrase) > 500 {
		return Result{}, bad("Введите фразу до 500 символов")
	}
	lower := strings.ToLower(phrase)
	incoming, outgoing := false, false
	for _, word := range []string{"куплю", "купим", "заплачу", "расход", "аренда", "потрачу", "оплачу"} {
		if strings.Contains(lower, word) {
			outgoing = true
		}
	}
	for _, word := range []string{"обещал", "заплатит", "придёт", "придет", "поступит", "получим"} {
		if strings.Contains(lower, word) {
			incoming = true
		}
	}
	if incoming == outgoing {
		return Result{}, bad("Уточните, деньги придут или уйдут")
	}
	direction := "out"
	if incoming {
		direction = "in"
	}
	dt, e := parsedEventDate(lower, now)
	if e != nil {
		return Result{}, e
	}
	amount, e := parsedEventAmount(dateDay.ReplaceAllString(dateISO.ReplaceAllString(lower, " "), " "))
	if e != nil {
		return Result{}, e
	}
	name := ""
	if match := clientName.FindStringSubmatch(phrase); len(match) > 0 {
		name = strings.TrimSpace(match[1])
	}
	return ok(Doc{"date": dt.Format("2006-01-02"), "amount": money(amount), "direction": direction, "title": phrase, "category": "other", "counterparty_name": name, "probability": float64(1), "confidence": .8, "parser": "rules", "source": "manual", "status": "expected"})
}

func parsedEventDate(phrase string, now time.Time) (time.Time, error) {
	iso := dateISO.FindAllStringSubmatch(phrase, -1)
	ordinal := dateDay.FindAllStringSubmatch(phrase, -1)
	if len(iso)+len(ordinal) != 1 {
		return time.Time{}, bad("Укажите одну дату: например, 20-го или 2026-11-20")
	}
	if len(iso) == 1 {
		return day(iso[0][1])
	}
	match := ordinal[0]
	n, _ := strconv.Atoi(match[1])
	if n < 1 || n > 31 {
		return time.Time{}, bad("Некорректный день месяца")
	}
	month := now.Month()
	for i, name := range strings.Fields("января февраля марта апреля мая июня июля августа сентября октября ноября декабря") {
		if match[2] == name {
			month = time.Month(i + 1)
		}
	}
	if match[3] != "" {
		year, _ := strconv.Atoi(match[3])
		dt := time.Date(year, month, n, 0, 0, 0, 0, time.UTC)
		if dt.Day() != n || dt.Month() != month {
			return time.Time{}, bad("Такой даты нет в выбранном месяце")
		}
		return dt, nil
	}
	// Search actual calendar dates; AddDate on Jan 30 would normalize Feb 30
	// into March 2. A request for the 30th must keep that day number.
	start := time.Date(now.Year(), month, 1, 0, 0, 0, 0, time.UTC)
	for i := 0; i < 12; i++ {
		candidate := start.AddDate(0, i, 0)
		if match[2] != "" {
			candidate = start.AddDate(i, 0, 0)
		}
		dt := time.Date(candidate.Year(), candidate.Month(), n, 0, 0, 0, 0, time.UTC)
		if dt.Month() == candidate.Month() && dt.Day() == n && !dt.Before(now) {
			return dt, nil
		}
	}
	return time.Time{}, bad("Такой даты нет в выбранном месяце")
}

func parsedEventAmount(phrase string) (float64, error) {
	type candidate struct{ number, unit string }
	all, monetary := []candidate{}, []candidate{}
	for _, loc := range amountLiteral.FindAllStringIndex(phrase, -1) {
		c := candidate{number: strings.TrimSpace(phrase[loc[0]:loc[1]])}
		if unit := amountUnit.FindStringSubmatch(strings.TrimSpace(phrase[loc[1]:])); len(unit) > 0 {
			c.unit = unit[1]
			monetary = append(monetary, c)
		}
		all = append(all, c)
	}
	if len(monetary) > 0 {
		all = monetary
	}
	if len(all) != 1 {
		return 0, bad("Укажите одну сумму платежа")
	}
	c := all[0]
	groups := strings.Fields(c.number)
	for i, group := range groups {
		integer := strings.FieldsFunc(group, func(r rune) bool { return strings.ContainsRune(".,eE", r) })
		if len(groups) > 1 && (len(integer) == 0 || (i == 0 && len(strings.TrimLeft(integer[0], "+-")) > 3) || (i > 0 && len(integer[0]) != 3)) {
			return 0, bad("Проверьте разделители суммы")
		}
	}
	raw := strings.Map(func(r rune) rune {
		if unicode.IsSpace(r) {
			return -1
		}
		return r
	}, c.number)
	amount, err := parseAmount(raw)
	if err != nil {
		return 0, err
	}
	if strings.HasPrefix(c.unit, "млн") || strings.HasPrefix(c.unit, "миллион") {
		amount *= 1e6
	} else if c.unit == "к" || strings.HasPrefix(c.unit, "тыс") {
		amount *= 1000
	}
	if amount <= 0 || amount > 1e13 {
		return 0, bad("Укажите положительную сумму")
	}
	return amount, nil
}
