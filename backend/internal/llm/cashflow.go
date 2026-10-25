package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
	"unicode"
	"unicode/utf8"
)

// CashflowFact deliberately excludes company, counterparty, document, free-text
// fields, identifiers, dates and money. The model only explains a mechanism;
// all financial figures and conditions come from the application.
type CashflowFact struct {
	Kind          string `json:"kind"`
	ClosesGap     bool   `json:"closes_gap"`
	Improves      bool   `json:"reduces_shortfall"`
	BeyondHorizon bool   `json:"deferred_beyond_horizon"`
}

type CashflowNarrator struct {
	Endpoint, Key, Model string
	Client               *http.Client
}

func NewCashflowNarrator(baseURL, key, model string) (*CashflowNarrator, error) {
	if baseURL == "" && key == "" && model == "" {
		return nil, nil
	}
	u, err := url.Parse(baseURL)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || model == "" {
		return nil, fmt.Errorf("CASHFLOW_LLM_BASE_URL and CASHFLOW_LLM_MODEL are required")
	}
	ip := net.ParseIP(u.Hostname())
	local := u.Hostname() == "localhost" || ip != nil && ip.IsLoopback()
	if u.Scheme != "https" && !(u.Scheme == "http" && local) || !local && key == "" {
		return nil, fmt.Errorf("cashflow LLM requires HTTPS and API key, or a loopback server")
	}
	return &CashflowNarrator{Endpoint: strings.TrimRight(baseURL, "/") + "/chat/completions", Key: key, Model: model,
		Client: &http.Client{Timeout: 3 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}, nil
}

func (n *CashflowNarrator) Explain(ctx context.Context, facts []CashflowFact) ([]string, error) {
	data, err := json.Marshal(facts)
	if err != nil {
		return nil, err
	}
	body, err := json.Marshal(map[string]any{
		"model": n.Model, "temperature": 0.2, "max_tokens": 1200,
		"response_format": map[string]string{"type": "json_object"},
		"messages": []map[string]string{
			{"role": "system", "content": `Ты объясняешь варианты управления денежным потоком. Верни JSON {"explanations":["..."]}: одно пояснение по-русски на каждый входной элемент в исходном порядке, до 350 символов. Объясни только механизм действия условно: «может помочь», «при согласовании». Не обещай результат, не придумывай факты, не давай новых советов, не указывай суммы, числа, даты, проценты, имена, ссылки. shift_supplier_payment — согласование отсрочки; accelerate_receivable — просьба об оплате раньше; overdraft — возможное финансирование с неизвестными условиями. Если reduces_shortfall=false, не утверждай уменьшение нехватки. При deferred_beyond_horizon=true обязательство сохраняется за горизонтом.`},
			{"role": "user", "content": string(data)},
		},
	})
	if err != nil {
		return nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, "POST", n.Endpoint, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	if n.Key != "" {
		req.Header.Set("Authorization", "Bearer "+n.Key)
	}
	res, err := n.Client.Do(req)
	if err != nil {
		return nil, err
	}
	defer res.Body.Close()
	if res.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("cashflow narrator status %d", res.StatusCode)
	}
	var response struct {
		Choices []struct {
			Message struct{ Content string }
		}
	}
	if err := json.NewDecoder(io.LimitReader(res.Body, 32<<10)).Decode(&response); err != nil || len(response.Choices) != 1 {
		return nil, fmt.Errorf("invalid narrator response")
	}
	var result struct{ Explanations []string }
	if err := json.Unmarshal([]byte(response.Choices[0].Message.Content), &result); err != nil || len(result.Explanations) != len(facts) {
		return nil, fmt.Errorf("invalid narrator explanations")
	}
	for _, explanation := range result.Explanations {
		if !validCashflowExplanation(explanation) {
			return nil, fmt.Errorf("invalid narrator explanation")
		}
	}
	return result.Explanations, nil
}

func validCashflowExplanation(s string) bool {
	if utf8.RuneCountInString(s) < 15 || utf8.RuneCountInString(s) > 350 || strings.ContainsAny(s, "<>%₽$") || strings.Contains(s, "://") {
		return false
	}
	for _, r := range s {
		if unicode.IsNumber(r) || unicode.IsControl(r) {
			return false
		}
	}
	return true
}
