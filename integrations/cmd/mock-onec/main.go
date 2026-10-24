// Command mock-onec serves synthetic 1C-shaped OData v3 data for local tests only.
package main

import (
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

func main() {
	username := os.Getenv("ONEC_ODATA_USERNAME")
	password := os.Getenv("ONEC_ODATA_PASSWORD")
	if username == "" || password == "" {
		log.Fatal("set mock credentials")
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /odata/standard.odata/Document_BankReceipt", func(w http.ResponseWriter, r *http.Request) {
		if !authorized(w, r, username, password) {
			return
		}
		if r.URL.Query().Get("$skiptoken") == "page2" {
			write(w, map[string]any{"d": map[string]any{"results": []any{
				map[string]any{"Ref_Key": "11111111-1111-1111-1111-111111111111", "Number": "ВХ-1", "Date": "2026-10-20T10:00:00", "ExecutionDate": "2026-10-20T11:00:00", "Amount": 1250.75, "Posted": true, "Account_Key": "bank-account-1", "Counterparty": map[string]any{"INN": "7800000000", "Description": "Покупатель"}, "PaymentPurpose": "Оплата заказа"},
				map[string]any{"Ref_Key": "33333333-3333-3333-3333-333333333333", "Number": "ВХ-2", "Date": "2026-10-21T10:00:00", "ExecutionDate": "2026-10-21T11:00:00", "Amount": 100, "Posted": false, "Account_Key": "bank-account-1"},
			}}})
			return
		}
		write(w, map[string]any{"d": map[string]any{"results": []any{
			map[string]any{"Ref_Key": "11111111-1111-1111-1111-111111111111", "Number": "ВХ-1", "Date": "2026-10-20T10:00:00", "ExecutionDate": "2026-10-20T11:00:00", "Amount": 1250.75, "Posted": true, "Account_Key": "bank-account-1", "Counterparty": map[string]any{"INN": "7800000000", "Description": "Покупатель"}, "PaymentPurpose": "Оплата заказа"},
		}, "__next": "?%24skiptoken=page2"}})
	})
	mux.HandleFunc("GET /odata/standard.odata/Document_BankPayment", func(w http.ResponseWriter, r *http.Request) {
		if !authorized(w, r, username, password) {
			return
		}
		write(w, map[string]any{"d": map[string]any{"results": []any{
			map[string]any{"Ref_Key": "22222222-2222-2222-2222-222222222222", "Number": "ИСХ-1", "Date": "2026-10-21T09:00:00", "ExecutionDate": "2026-10-21T10:00:00", "Amount": 850.10, "Posted": true, "Account_Key": "bank-account-1", "Counterparty": map[string]any{"INN": "7700000001", "Description": "Поставщик"}, "PaymentPurpose": "Оплата счёта"},
		}}})
	})
	srv := &http.Server{Addr: "127.0.0.1:8092", Handler: mux, ReadHeaderTimeout: 5 * time.Second}
	log.Print("synthetic 1C OData mock listening on loopback")
	if err := srv.ListenAndServe(); err != nil {
		log.Fatal("mock failed")
	}
}

func authorized(w http.ResponseWriter, r *http.Request, username, password string) bool {
	u, p, ok := r.BasicAuth()
	if !ok || u != username || p != password {
		w.Header().Set("WWW-Authenticate", `Basic realm="mock-1c"`)
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return false
	}
	if !strings.EqualFold(r.URL.Query().Get("$format"), "json") && r.URL.Query().Get("$skiptoken") == "" {
		http.Error(w, "format required", 400)
		return false
	}
	return true
}

func write(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(v)
}
