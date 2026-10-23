// Package llm — адаптер языковой модели. Промпты: человек с ChatGPT,
// интеграция: Бэк 1/Бэк 2.
//
// По умолчанию российский провайдер (GigaChat / YandexGPT): назначения
// платежей содержат ФИО, и по 152-ФЗ отправлять их за рубеж без
// обезличивания нельзя.
//
// TODO: провайдеры gigachat, yandexgpt; обезличивание ИНН/ФИО перед отправкой.
package llm

import (
	"context"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/registry"
)

type Request struct {
	System string
	Prompt string
	// JSONSchema — если задан, ответ должен быть JSON по схеме.
	JSONSchema  map[string]any
	Temperature float64
}

type Response struct {
	Text string
}

type LLM interface {
	Complete(ctx context.Context, req Request) (Response, error)
}

var Providers = registry.New[LLM]()
