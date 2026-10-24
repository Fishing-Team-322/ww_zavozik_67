package product

import (
	"regexp"
	"strings"
	"time"
)

var amountPhrase = regexp.MustCompile(`(?i)([0-9][0-9\s]*(?:[.,][0-9]{1,2})?)\s*(млн|миллион[а-я]*|тыс[а-я.]*|к(?:\s|$)|руб[а-я.]*|₽)`)
var dateISO = regexp.MustCompile(`\b(20[0-9]{2}-[01][0-9]-[0-3][0-9])\b`)
var dateDay = regexp.MustCompile(`\b([0-3]?[0-9])(?:-го|\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря))`)
var plainNumber = regexp.MustCompile(`[0-9][0-9 ]*(?:[.,][0-9]{1,2})?`)
var clientName = regexp.MustCompile(`(?i)клиент\s+(.+?)\s+(?:обещал|заплатит|переведёт|переведет)`)

func (s *Service) parseEvent(b Doc) (Result, error) {
	if e := fields(b, "text"); e != nil {
		return Result{}, e
	}
	phrase := text(b, "text")
	if len(phrase) == 0 || len(phrase) > 1500 {
		return Result{}, bad("Введите фразу до 500 символов")
	}
	lower := strings.ToLower(phrase)
	direction := ""
	for _, word := range []string{"куплю", "купим", "заплачу", "расход", "аренда", "потрачу", "оплачу"} {
		if strings.Contains(lower, word) {
			direction = "out"
		}
	}
	for _, word := range []string{"обещал", "заплатит", "придёт", "придет", "поступит", "получим"} {
		if strings.Contains(lower, word) {
			direction = "in"
		}
	}
	if direction == "" {
		return Result{}, bad("Уточните, деньги придут или уйдут")
	}
	now := today()
	var dt time.Time
	if match := dateISO.FindStringSubmatch(lower); len(match) > 0 {
		var e error
		dt, e = day(match[1])
		if e != nil {
			return Result{}, e
		}
	} else if match := dateDay.FindStringSubmatch(lower); len(match) > 0 {
		n, _ := parseAmount(match[1])
		month := now.Month()
		year := now.Year()
		months := strings.Fields("января февраля марта апреля мая июня июля августа сентября октября ноября декабря")
		for i, m := range months {
			if match[2] == m {
				month = time.Month(i + 1)
			}
		}
		dt = time.Date(year, month, int(n), 0, 0, 0, 0, time.UTC)
		if dt.Day() != int(n) {
			return Result{}, bad("Такой даты нет в выбранном месяце")
		}
		if dt.Before(now) {
			if match[2] != "" {
				dt = dt.AddDate(1, 0, 0)
			} else {
				dt = dt.AddDate(0, 1, 0)
			}
		}
	} else {
		return Result{}, bad("Укажите дату: например, 20-го или 2026-11-20")
	}
	amount := float64(0)
	if match := amountPhrase.FindStringSubmatch(lower); len(match) > 0 {
		v, e := parseAmount(match[1])
		if e != nil {
			return Result{}, e
		}
		amount = v
		unit := match[2]
		if strings.HasPrefix(unit, "млн") || strings.HasPrefix(unit, "миллион") {
			amount *= 1e6
		} else if strings.TrimSpace(unit) == "к" || strings.HasPrefix(unit, "тыс") {
			amount *= 1000
		}
	} else {
		withoutDate := dateISO.ReplaceAllString(dateDay.ReplaceAllString(lower, ""), "")
		raw := plainNumber.FindString(withoutDate)
		v, e := parseAmount(raw)
		if e != nil {
			return Result{}, bad("Укажите сумму платежа")
		}
		amount = v
	}
	if amount <= 0 || amount > 1e13 {
		return Result{}, bad("Укажите положительную сумму")
	}
	name := ""
	if match := clientName.FindStringSubmatch(phrase); len(match) > 0 {
		name = strings.TrimSpace(match[1])
	}
	return ok(Doc{"date": dt.Format("2006-01-02"), "amount": money(amount), "direction": direction, "title": phrase, "category": "other", "counterparty_name": name, "probability": float64(1), "confidence": .8, "parser": "rules", "source": "manual", "status": "expected"})
}
