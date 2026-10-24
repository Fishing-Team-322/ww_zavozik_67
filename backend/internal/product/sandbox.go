package product

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

// Only installed by explicit operator configuration on loopback public origins.
// No request is sent to external suppliers; synthetic credentials must be used.
type sandboxTransport struct{}

func (sandboxTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	status, body := 200, ""
	switch r.URL.Host {
	case "finance-api.wildberries.ru":
		if r.Header.Get("Authorization") != "sandbox-key" {
			status = 401
			body = `{}`
			break
		}
		var input struct {
			RRDID int `json:"rrdId"`
		}
		if e := json.NewDecoder(r.Body).Decode(&input); e != nil {
			return nil, e
		}
		if input.RRDID > 0 {
			status = 204
		} else {
			body = `[{"reportId":9001,"rrdId":1,"currency":"RUB","docTypeName":"Продажа","forPay":"100.05","acquiringFee":"2.01","deliveryRub":"5.00"},{"reportId":9001,"rrdId":2,"currency":"RUB","docTypeName":"Возврат","forPay":"-30.00"}]`
		}
	case "api-seller.ozon.ru":
		if r.Header.Get("Api-Key") != "sandbox-key" || r.Header.Get("Client-Id") != "sandbox-client" {
			status = 401
			body = `{}`
			break
		}
		var input struct {
			Page int `json:"page"`
		}
		if e := json.NewDecoder(r.Body).Decode(&input); e != nil {
			return nil, e
		}
		if input.Page == 1 {
			body = `{"result":{"page_count":2,"operations":[{"operation_id":9001,"operation_type":"OperationAgentDeliveredToCustomer","operation_date":"2026-10-01T00:00:00Z","amount":100.05,"accruals_for_sale":120.05,"sale_commission":-20,"delivery_charge":0}]}}`
		} else {
			body = `{"result":{"page_count":2,"operations":[{"operation_id":9002,"operation_type":"ClientReturn","operation_date":"2026-10-02T00:00:00Z","amount":-30.01}]}}`
		}
	case "sheets.googleapis.com":
		if r.Header.Get("X-Goog-Api-Key") != "sandbox-key" && r.Header.Get("Authorization") != "Bearer sandbox-key" {
			status = 403
			body = `{}`
			break
		}
		body = fmt.Sprintf(`{"values":[["date","amount","direction","counterparty_name","purpose","balance_eod"],[%q,"100","in","Sandbox customer","SYNTHETIC SANDBOX","1000"]]}`, time.Now().UTC().Format("2006-01-02"))
	case "suggestions.dadata.ru":
		var input struct {
			Query string `json:"query"`
		}
		if e := json.NewDecoder(r.Body).Decode(&input); e != nil {
			return nil, e
		}
		body = fmt.Sprintf(`{"suggestions":[{"value":"Sandbox registry fixture","data":{"inn":%q,"ogrn":"1226100018561","name":{"full_with_opf":"Sandbox registry fixture"},"state":{"status":"ACTIVE"}}}]}`, input.Query)
	default:
		return nil, fmt.Errorf("sandbox blocks external request")
	}
	return &http.Response{StatusCode: status, Header: http.Header{"Content-Type": []string{"application/json"}}, Body: io.NopCloser(strings.NewReader(body)), Request: r}, nil
}
