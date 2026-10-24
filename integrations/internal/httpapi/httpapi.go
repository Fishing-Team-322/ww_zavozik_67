package httpapi

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/importcsv"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/dadata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecbank"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/service"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

const maxRequestBytes = onecbank.MaxFileBytes + 64<<10

type API struct {
	Store          store.Repository
	CompanyID      string
	Ready          func(context.Context) error
	OneCConfig     *onecodata.Config
	OneCPlanConfig *onecodata.PlanConfig
	OneCClient     onecodata.Client
	DaDataClient   *dadata.Client
	SyncToken      string
}

func (a API) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		if a.Ready != nil && a.Ready(r.Context()) != nil {
			writeError(w, 503, "not_ready", "Storage unavailable")
			return
		}
		writeJSON(w, 200, map[string]string{"status": "ready"})
	})
	mux.HandleFunc("GET /v1/providers", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, providers.List(a.OneCConfig != nil, a.DaDataClient != nil))
	})
	mux.HandleFunc("GET /v1/integrations/capabilities", func(w http.ResponseWriter, r *http.Request) {
		if !authorized(r, a.SyncToken) {
			writeError(w, 401, "unauthorized", "Invalid authorization")
			return
		}
		writeJSON(w, 200, map[string]any{"schema_version": contracts.SchemaVersion, "company_id": a.CompanyID, "sources": []string{"onec_bank_file", "onec_odata", "dadata_party", "fns_debt_snapshot", "tax_calendar", "wildberries_finance", "ozon_finance", "csv"}, "storage": "postgresql"})
	})
	mux.HandleFunc("POST /v1/import/onec-bank", a.importOneC)
	mux.HandleFunc("POST /v1/import/csv", a.importCSV)
	mux.HandleFunc("POST /v1/sync/onec-odata", a.trackSync("onec_odata", a.syncOneC))
	mux.HandleFunc("POST /v1/sync/onec-plans", a.trackSync("onec_plans", a.syncOneCPlans))
	mux.HandleFunc("POST /v1/enrich/dadata-party", a.enrichDaData)
	mux.HandleFunc("GET /v1/batches/{companyId}", a.batches)
	mux.HandleFunc("GET /v1/operations/{companyId}", a.operations)
	mux.HandleFunc("GET /v1/planned-events/{companyId}", a.plannedEvents)
	mux.HandleFunc("GET /v1/sync-runs/{companyId}", a.syncRuns)
	return mux
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(code int) { w.status = code; w.ResponseWriter.WriteHeader(code) }
func (a API) trackSync(source string, next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		if !authorized(r, a.SyncToken) {
			next(w, r)
			return
		}
		tracked := &statusWriter{ResponseWriter: w, status: 200}
		next(tracked, r)
		if a.Store != nil && a.CompanyID != "" {
			_ = a.Store.RecordRun(a.CompanyID, source, tracked.status)
		}
	}
}

func (a API) companyAllowed(w http.ResponseWriter, r *http.Request) bool {
	id := r.PathValue("companyId")
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return false
	}
	if id == "" || len(id) > 128 || strings.TrimSpace(id) != id {
		writeError(w, 400, "invalid_company_id", "Invalid company ID")
		return false
	}
	if a.CompanyID != "" && id != a.CompanyID {
		writeError(w, 403, "forbidden", "Company access denied")
		return false
	}
	return true
}

func (a API) operations(w http.ResponseWriter, r *http.Request) {
	if !a.companyAllowed(w, r) {
		return
	}
	id := r.PathValue("companyId")
	items, err := a.Store.GetOperations(id)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read operations")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": id, "operations": items})
}

func (a API) syncRuns(w http.ResponseWriter, r *http.Request) {
	if !a.companyAllowed(w, r) {
		return
	}
	id := r.PathValue("companyId")
	items, err := a.Store.GetRuns(id)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read sync runs")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": id, "sync_runs": items})
}

func (a API) importCSV(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 11<<20)
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		writeError(w, 400, "invalid_request", "Malformed CSV upload")
		return
	}
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	if a.CompanyID != "" && r.FormValue("company_id") != a.CompanyID {
		writeError(w, 403, "forbidden", "Company access denied")
		return
	}
	var mapping importcsv.Mapping
	if err := json.Unmarshal([]byte(r.FormValue("mapping")), &mapping); err != nil {
		writeError(w, 400, "invalid_mapping", "Expected JSON mapping")
		return
	}
	files := r.MultipartForm.File["file"]
	if len(files) != 1 {
		writeError(w, 400, "invalid_file", "Exactly one CSV file is required")
		return
	}
	file, err := files[0].Open()
	if err != nil {
		writeError(w, 400, "invalid_file", "Cannot open CSV file")
		return
	}
	defer file.Close()
	preview, err := importcsv.Parse(file, r.FormValue("company_id"), mapping)
	if err != nil {
		writeError(w, 400, "invalid_csv", err.Error())
		return
	}
	if r.FormValue("mode") == "commit" {
		if len(preview.Issues) != 0 {
			writeJSON(w, 422, preview)
			return
		}
		preview.Batch, err = a.Store.Save(preview.Batch)
		if err != nil {
			writeError(w, 500, "storage_error", "Cannot save CSV import")
			return
		}
	} else if r.FormValue("mode") != "preview" {
		writeError(w, 400, "invalid_mode", "Expected preview or commit")
		return
	}
	writeJSON(w, 200, preview)
}

func (a API) syncOneCPlans(w http.ResponseWriter, r *http.Request) {
	if a.OneCPlanConfig == nil || a.SyncToken == "" {
		writeError(w, 503, "not_configured", "1C planned events are not configured")
		return
	}
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	if a.CompanyID != "" && a.OneCPlanConfig.CompanyID != a.CompanyID {
		writeError(w, 403, "forbidden", "Company access denied")
		return
	}
	if r.ContentLength > 0 {
		writeError(w, 400, "invalid_request", "Request body must be empty")
		return
	}
	batch, err := (service.Importer{Store: a.Store}).OneCPlans(r.Context(), a.OneCClient, *a.OneCPlanConfig)
	if err != nil {
		switch {
		case errors.Is(err, onecodata.ErrAuth):
			writeError(w, 502, "upstream_auth_failed", "1C authentication failed")
		case errors.Is(err, onecodata.ErrLimit):
			writeError(w, 502, "upstream_limit", "1C response exceeds limit")
		default:
			writeError(w, 502, "upstream_failed", "1C planned sync failed")
		}
		return
	}
	writeJSON(w, 200, batch)
}

func (a API) plannedEvents(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	id := r.PathValue("companyId")
	if a.CompanyID != "" && id != a.CompanyID {
		writeError(w, 403, "forbidden", "Company access denied")
		return
	}
	if id == "" || len(id) > 128 || strings.TrimSpace(id) != id {
		writeError(w, 400, "invalid_company_id", "Invalid company ID")
		return
	}
	plans, err := a.Store.GetPlans(id)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read plans")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": id, "planned_events": plans})
}

func (a API) syncOneC(w http.ResponseWriter, r *http.Request) {
	if a.OneCConfig == nil || a.SyncToken == "" {
		writeError(w, 503, "not_configured", "1C OData is not configured")
		return
	}
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	if a.CompanyID != "" && a.OneCConfig.CompanyID != a.CompanyID {
		writeError(w, 403, "forbidden", "Company access denied")
		return
	}
	if r.ContentLength > 0 {
		writeError(w, 400, "invalid_request", "Request body must be empty")
		return
	}
	batch, err := (service.Importer{Store: a.Store}).OneCOData(r.Context(), a.OneCClient, *a.OneCConfig)
	if err != nil {
		switch {
		case errors.Is(err, onecodata.ErrAuth):
			writeError(w, 502, "upstream_auth_failed", "1C authentication failed")
		case errors.Is(err, onecodata.ErrLimit):
			writeError(w, 502, "upstream_limit", "1C response exceeds limit")
		default:
			writeError(w, 502, "upstream_failed", "1C sync failed")
		}
		return
	}
	writeJSON(w, 200, batch)
}

func (a API) enrichDaData(w http.ResponseWriter, r *http.Request) {
	if a.DaDataClient == nil || a.SyncToken == "" {
		writeError(w, 503, "not_configured", "DaData is not configured")
		return
	}
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 1024)
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	var input struct {
		INN        string `json:"inn"`
		Identifier string `json:"identifier"`
	}
	if decoder.Decode(&input) != nil || decoder.Decode(new(any)) != io.EOF {
		writeError(w, 400, "invalid_request", "Expected JSON with INN")
		return
	}
	identifier := input.Identifier
	if identifier == "" {
		identifier = input.INN
	}
	if input.INN != "" && input.Identifier != "" {
		writeError(w, 400, "invalid_request", "Specify either inn or identifier")
		return
	}
	party, err := a.DaDataClient.Lookup(r.Context(), identifier)
	if err != nil {
		switch {
		case errors.Is(err, dadata.ErrInvalidINN):
			writeError(w, 400, "invalid_identifier", "Invalid INN or OGRN")
		case errors.Is(err, dadata.ErrNotFound):
			writeError(w, 404, "not_found", "Company not found")
		case errors.Is(err, dadata.ErrAuth):
			writeError(w, 502, "upstream_auth_failed", "DaData authentication failed")
		case errors.Is(err, dadata.ErrRateLimited):
			writeError(w, 503, "upstream_rate_limited", "DaData rate limit exceeded")
		default:
			writeError(w, 502, "upstream_failed", "DaData lookup failed")
		}
		return
	}
	writeJSON(w, 200, party)
}

func authorized(r *http.Request, token string) bool {
	want := "Bearer " + token
	got := r.Header.Get("Authorization")
	return token != "" && len(got) == len(want) && subtle.ConstantTimeCompare([]byte(got), []byte(want)) == 1
}

func (a API) importOneC(w http.ResponseWriter, r *http.Request) {
	if a.SyncToken == "" {
		writeError(w, 503, "not_configured", "Operator token is not configured")
		return
	}
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	if !strings.HasPrefix(r.Header.Get("Content-Type"), "multipart/form-data;") {
		writeError(w, 400, "invalid_request", "Expected multipart form")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxRequestBytes)
	err := r.ParseMultipartForm(1 << 20)
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	if err != nil {
		var maxErr *http.MaxBytesError
		if errors.As(err, &maxErr) {
			writeError(w, 413, "too_large", "Upload exceeds limit")
		} else {
			writeError(w, 400, "invalid_request", "Malformed multipart form")
		}
		return
	}
	id := contracts.Identity{CompanyID: r.FormValue("company_id"), CompanyINN: r.FormValue("company_inn"), CompanyAccount: r.FormValue("company_account")}
	if a.CompanyID != "" && id.CompanyID != a.CompanyID {
		writeError(w, 403, "forbidden", "Company access denied")
		return
	}
	if err := id.Validate(); err != nil {
		writeError(w, 400, "invalid_identity", err.Error())
		return
	}
	files := r.MultipartForm.File["file"]
	if len(files) != 1 {
		writeError(w, 400, "invalid_file", "Exactly one file is required")
		return
	}
	file, err := files[0].Open()
	if err != nil {
		writeError(w, 400, "invalid_file", "Cannot open upload")
		return
	}
	defer file.Close()
	batch, err := (service.Importer{Store: a.Store}).OneCBank(r.Context(), file, id)
	if err != nil {
		switch {
		case errors.Is(err, onecbank.ErrTooLarge):
			writeError(w, 413, "too_large", "File exceeds limit")
		case errors.Is(err, onecbank.ErrInvalid):
			writeError(w, 400, "invalid_file", "Invalid 1CClientBankExchange file")
		case errors.Is(err, io.EOF):
			writeError(w, 400, "invalid_file", "Empty file")
		default:
			writeError(w, 500, "internal_error", "Import failed")
		}
		return
	}
	writeJSON(w, 200, batch)
}

func (a API) batches(w http.ResponseWriter, r *http.Request) {
	if a.SyncToken == "" {
		writeError(w, 503, "not_configured", "Operator token is not configured")
		return
	}
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	id := r.PathValue("companyId")
	if a.CompanyID != "" && id != a.CompanyID {
		writeError(w, 403, "forbidden", "Company access denied")
		return
	}
	if id == "" || len(id) > 128 || strings.TrimSpace(id) != id {
		writeError(w, 400, "invalid_company_id", "Invalid company ID")
		return
	}
	batches, err := a.Store.GetBatches(id)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read batches")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": id, "batches": batches})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.Header().Set("X-Content-Type-Options", "nosniff")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, code, message string) {
	writeJSON(w, status, map[string]string{"code": code, "message": message})
}
