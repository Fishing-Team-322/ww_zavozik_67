package httpapi

import (
	"errors"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/intelligence"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fnsregistry"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

func (a API) registryStore(w http.ResponseWriter, r *http.Request) (store.RegistryStore, bool) {
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return nil, false
	}
	if a.CompanyID == "" {
		writeError(w, 503, "not_configured", "Company is not configured")
		return nil, false
	}
	s, ok := a.Store.(store.RegistryStore)
	if !ok {
		writeError(w, 503, "not_configured", "Registry storage is unavailable")
		return nil, false
	}
	return s, true
}
func (a API) registryUpload(w http.ResponseWriter, r *http.Request) (store.RegistryStore, *os.File, int64, bool) {
	s, ok := a.registryStore(w, r)
	if !ok {
		return nil, nil, 0, false
	}
	r.Body = http.MaxBytesReader(w, r.Body, fnsregistry.MaxUploadBytes+(64<<10))
	if err := r.ParseMultipartForm(1 << 20); err != nil {
		var big *http.MaxBytesError
		if errors.As(err, &big) {
			writeError(w, 413, "too_large", "Registry upload exceeds limit")
		} else {
			writeError(w, 400, "invalid_request", "Malformed multipart upload")
		}
		return nil, nil, 0, false
	}
	if r.MultipartForm != nil {
		defer r.MultipartForm.RemoveAll()
	}
	if r.FormValue("company_id") != a.CompanyID {
		writeError(w, 403, "forbidden", "Company access denied")
		return nil, nil, 0, false
	}
	files := r.MultipartForm.File["file"]
	if len(files) != 1 || files[0].Size <= 0 || files[0].Size > fnsregistry.MaxUploadBytes {
		writeError(w, 400, "invalid_file", "Exactly one bounded file is required")
		return nil, nil, 0, false
	}
	f, err := files[0].Open()
	if err != nil {
		writeError(w, 400, "invalid_file", "Cannot open upload")
		return nil, nil, 0, false
	}
	defer f.Close()
	tmp, err := os.CreateTemp("", "fns-upload-*.bin")
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot buffer upload")
		return nil, nil, 0, false
	}
	n, err := io.Copy(tmp, io.LimitReader(f, fnsregistry.MaxUploadBytes+1))
	if err != nil || n > fnsregistry.MaxUploadBytes {
		tmp.Close()
		os.Remove(tmp.Name())
		writeError(w, 413, "too_large", "Registry upload exceeds limit")
		return nil, nil, 0, false
	}
	return s, tmp, n, true
}
func (a API) importRegistryPDF(want string) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s, f, n, ok := a.registryUpload(w, r)
		if !ok {
			return
		}
		defer f.Close()
		defer os.Remove(f.Name())
		rec, err := fnsregistry.ParsePDF(f, n, time.Now())
		if err != nil {
			writeError(w, 422, "invalid_pdf", err.Error())
			return
		}
		if rec.Source != want {
			writeError(w, 422, "wrong_registry", "PDF registry type does not match route")
			return
		}
		rec, status, err := s.SaveRegistry(r.Context(), a.CompanyID, rec)
		if err != nil {
			writeError(w, 500, "storage_error", "Cannot save registry record")
			return
		}
		writeJSON(w, 200, map[string]any{"company_id": a.CompanyID, "status": status, "record": rec})
	}
}
func (a API) importRegistryXML(w http.ResponseWriter, r *http.Request) {
	s, f, n, ok := a.registryUpload(w, r)
	if !ok {
		return
	}
	defer f.Close()
	defer os.Remove(f.Name())
	var header [4]byte
	if _, err := f.ReadAt(header[:], 0); err != nil {
		writeError(w, 422, "invalid_xml", "Empty registry file")
		return
	}
	zipFile := string(header[:]) == "PK\x03\x04"
	if !zipFile && n > 32<<20 {
		writeError(w, 413, "too_large", "XML exceeds limit")
		return
	}
	parse := func(emit func(fnsregistry.Record) error) (int, error) {
		if zipFile {
			return fnsregistry.ParseZIP(r.Context(), f, n, time.Now(), emit)
		}
		if _, err := f.Seek(0, 0); err != nil {
			return 0, err
		}
		return fnsregistry.ParseXML(r.Context(), f, time.Now(), emit)
	}
	if _, err := parse(nil); err != nil {
		writeError(w, 422, "invalid_xml", err.Error())
		return
	}
	changed, duplicates, outdated := 0, 0, 0
	count, err := parse(func(rec fnsregistry.Record) error {
		_, status, e := s.SaveRegistry(r.Context(), a.CompanyID, rec)
		if e != nil {
			return e
		}
		switch status {
		case "updated":
			changed++
		case "duplicate":
			duplicates++
		case "outdated":
			outdated++
		}
		return nil
	})
	if err != nil {
		writeError(w, 500, "storage_error", "Registry import failed")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": a.CompanyID, "records": count, "changed": changed, "duplicates": duplicates, "outdated": outdated})
}
func (a API) registryCurrent(w http.ResponseWriter, r *http.Request) {
	s, ok := a.registryStore(w, r)
	if !ok {
		return
	}
	id := r.PathValue("inn")
	if !fnsregistry.ValidIdentifier(id) {
		writeError(w, 400, "invalid_identifier", "Invalid INN or OGRN")
		return
	}
	recs, err := s.GetRegistry(r.Context(), a.CompanyID, id)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read registry")
		return
	}
	if len(recs) == 0 {
		writeError(w, 404, "not_found", "Registry record not found")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": a.CompanyID, "records": recs})
}
func (a API) registryHistory(w http.ResponseWriter, r *http.Request) {
	s, ok := a.registryStore(w, r)
	if !ok {
		return
	}
	id := r.PathValue("inn")
	if !fnsregistry.ValidIdentifier(id) {
		writeError(w, 400, "invalid_identifier", "Invalid INN or OGRN")
		return
	}
	recs, err := s.RegistryHistory(r.Context(), a.CompanyID, id)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read registry history")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": a.CompanyID, "records": recs})
}
func (a API) intelligence(w http.ResponseWriter, r *http.Request) {
	s, ok := a.registryStore(w, r)
	if !ok {
		return
	}
	id := strings.TrimSpace(r.PathValue("inn"))
	if !fnsregistry.ValidIdentifier(id) {
		writeError(w, 400, "invalid_identifier", "Invalid INN or OGRN")
		return
	}
	recs, err := s.GetRegistry(r.Context(), a.CompanyID, id)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read registry")
		return
	}
	parties, err := a.Store.GetCounterparties(a.CompanyID)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read counterparties")
		return
	}
	risks, err := a.Store.GetRisks(a.CompanyID)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read risks")
		return
	}
	p := intelligence.Build(id, recs, parties, risks, time.Now().UTC())
	writeJSON(w, 200, map[string]any{"company_id": a.CompanyID, "profile": p})
}

func (a API) syncFNS(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	if a.FNSSync == nil || a.FNSSync.CompanyID != a.CompanyID {
		writeError(w, 503, "not_configured", "FNS open data sync is not configured")
		return
	}
	if r.ContentLength > 0 {
		writeError(w, 400, "invalid_request", "Request body must be empty")
		return
	}
	result, err := a.FNSSync.Run(r.Context())
	if err != nil {
		if strings.Contains(err.Error(), "already running") {
			writeError(w, 409, "already_running", "FNS sync is already running")
		} else {
			writeError(w, 502, "sync_failed", "FNS open data sync failed")
		}
		return
	}
	writeJSON(w, 200, result)
}
func (a API) fnsStatus(w http.ResponseWriter, r *http.Request) {
	if !authorized(r, a.SyncToken) {
		writeError(w, 401, "unauthorized", "Invalid authorization")
		return
	}
	db, ok := a.Store.(*store.Postgres)
	if !ok || a.CompanyID == "" {
		writeError(w, 503, "not_configured", "FNS status storage is unavailable")
		return
	}
	state, err := db.GetDatasetState(r.Context(), a.CompanyID)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read FNS status")
		return
	}
	runs, err := db.GetDatasetRuns(r.Context(), a.CompanyID)
	if err != nil {
		writeError(w, 500, "storage_error", "Cannot read FNS runs")
		return
	}
	writeJSON(w, 200, map[string]any{"company_id": a.CompanyID, "configured": a.FNSSync != nil, "last_success": state, "runs": runs})
}
