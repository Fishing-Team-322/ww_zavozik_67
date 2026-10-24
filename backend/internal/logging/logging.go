// Package logging — JSON-логи через slog. Чувствительные типы домена
// редактируются сами (domain.Money и др.); здесь — страховка по ключам на
// случай, если кто-то залогирует сырую строку или число.
package logging

import (
	"log/slog"
	"os"
	"strings"
)

var sensitiveKeys = map[string]bool{
	"amount": true, "balance": true, "inn": true, "purpose": true,
	"counterparty": true, "counterparty_name": true, "name": true,
	"password": true, "token": true, "authorization": true, "email": true,
}

func New(level string) *slog.Logger {
	var lvl slog.Level
	if err := lvl.UnmarshalText([]byte(level)); err != nil {
		lvl = slog.LevelInfo
	}
	return slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level:       lvl,
		ReplaceAttr: redact,
	}))
}

func redact(_ []string, a slog.Attr) slog.Attr {
	if sensitiveKeys[strings.ToLower(a.Key)] {
		return slog.String(a.Key, "[REDACTED]")
	}
	return a
}
