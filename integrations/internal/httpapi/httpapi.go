package httpapi

import (
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/dadata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecbank"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/service"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

const maxRequestBytes = onecbank.MaxFileBytes + 64<<10

type API struct {
	Store        *store.Memory
	OneCConfig   *onecodata.Config
	OneCClient   onecodata.Client
	DaDataClient *dadata.Client
	SyncToken    string
}

func (a API) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /v1/providers", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, providers.List(a.OneCConfig != nil, a.DaDataClient != nil))
	})
	mux.HandleFunc("POST /v1/import/onec-bank", a.importOneC)
	mux.HandleFunc("POST /v1/sync/onec-odata", a.syncOneC)
	mux.HandleFunc("POST /v1/enrich/dadata-party", a.enrichDaData)
	mux.HandleFunc("GET /v1/batches/{companyId}", a.batches)
	return mux
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
		INN string `json:"inn"`
	}
	if decoder.Decode(&input) != nil || decoder.Decode(new(any)) != io.EOF {
		writeError(w, 400, "invalid_request", "Expected JSON with INN")
		return
	}
	party, err := a.DaDataClient.Lookup(r.Context(), input.INN)
	if err != nil {
		switch {
		case errors.Is(err, dadata.ErrInvalidINN):
			writeError(w, 400, "invalid_inn", "Invalid INN")
		case errors.Is(err, dadata.ErrNotFound):
			writeError(w, 404, "not_found", "Company not found")
		case errors.Is(err, dadata.ErrAuth):
			writeError(w, 502, "upstream_auth_failed", "DaData authentication or quota failed")
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
	if id == "" || len(id) > 128 || strings.TrimSpace(id) != id {
		writeError(w, 400, "invalid_company_id", "Invalid company ID")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": id, "batches": a.Store.Batches(id)})
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
