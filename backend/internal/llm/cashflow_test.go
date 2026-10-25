package llm

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCashflowNarratorRequestAndValidation(t *testing.T) {
	for _, tc := range []struct {
		content string
		valid   bool
	}{
		{`{"explanations":["При согласовании отсрочка может помочь сохранить деньги для ближайших платежей."]}`, true},
		{`{"explanations":["Гарантированно получите 50000 рублей завтра."]}`, false},
		{`{"explanations":[]}`, false},
		{`not-json`, false},
	} {
		t.Run(tc.content, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/v1/chat/completions" || r.Header.Get("Authorization") != "Bearer synthetic-test-key" {
					t.Error("incorrect narrator request", r.URL.Path)
				}
				var body map[string]any
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
					t.Error(err)
				}
				messages := body["messages"].([]any)
				payload := messages[1].(map[string]any)["content"].(string)
				if strings.Contains(payload, "company") || strings.Contains(payload, "amount") || strings.Contains(payload, "event_id") {
					t.Error("unexpected financial payload", payload)
				}
				json.NewEncoder(w).Encode(map[string]any{"choices": []any{map[string]any{"message": map[string]any{"content": tc.content}}}})
			}))
			defer server.Close()
			n, err := NewCashflowNarrator(server.URL+"/v1", "synthetic-test-key", "test-model")
			if err != nil {
				t.Fatal(err)
			}
			_, err = n.Explain(context.Background(), []CashflowFact{{Kind: "shift_supplier_payment", Improves: true}})
			if (err == nil) != tc.valid {
				t.Fatalf("valid=%v error=%v", tc.valid, err)
			}
		})
	}
}

func TestCashflowNarratorUnavailable(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(429) }))
	defer server.Close()
	n, _ := NewCashflowNarrator(server.URL, "", "test")
	if _, err := n.Explain(context.Background(), []CashflowFact{{Kind: "overdraft"}}); err == nil {
		t.Fatal("rate limit must return an error for built-in fallback")
	}
	if n, err := NewCashflowNarrator("", "", ""); n != nil || err != nil {
		t.Fatal("disabled narrator", n, err)
	}
	if _, err := NewCashflowNarrator("http://remote.example/v1", "key", "test"); err == nil {
		t.Fatal("remote plaintext accepted")
	}
}
