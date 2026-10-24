// Package obligationapi is our own persistent demonstration bank/accounting API.
// It supplies future schedules; it does not claim access to a real bank account.
package obligationapi

import (
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sync"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/obligations"
)

type API struct {
	mu     sync.Mutex
	secret [32]byte
	admin  [32]byte
	path   string
	feeds  map[string]obligations.Feed
}

func New(token, adminToken, path string) (*API, error) {
	if len(token) < 32 || len(adminToken) < 32 || token == adminToken || path == "" {
		return nil, errors.New("distinct 32-character read/admin tokens and data file are required")
	}
	a := &API{secret: sha256.Sum256([]byte("Bearer " + token)), admin: sha256.Sum256([]byte("Bearer " + adminToken)), path: path, feeds: map[string]obligations.Feed{}}
	file, e := os.Open(path)
	if errors.Is(e, os.ErrNotExist) {
		return a, nil
	}
	if e != nil {
		return nil, errors.New("cannot open obligation store")
	}
	defer file.Close()
	decoder := json.NewDecoder(io.LimitReader(file, 32<<20))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&a.feeds) != nil || a.feeds == nil || decoder.Decode(new(any)) != io.EOF {
		return nil, errors.New("invalid obligation store")
	}
	return a, nil
}

func (a *API) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		write(w, 200, map[string]string{"status": "ok", "data_mode": "demo"})
	})
	mux.HandleFunc("GET /v1/companies/{inn}/{kind}/obligations", a.get)
	mux.HandleFunc("PUT /v1/companies/{inn}/{kind}/obligations", a.put)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/healthz" {
			provided := sha256.Sum256([]byte(r.Header.Get("Authorization")))
			allowed := subtle.ConstantTimeCompare(a.admin[:], provided[:]) == 1
			if r.Method == "GET" {
				allowed = allowed || subtle.ConstantTimeCompare(a.secret[:], provided[:]) == 1
			}
			if !allowed {
				write(w, 401, map[string]string{"error": "unauthorized"})
				return
			}
		}
		mux.ServeHTTP(w, r)
	})
}

func (a *API) get(w http.ResponseWriter, r *http.Request) {
	a.mu.Lock()
	feed, ok := a.feeds[r.PathValue("inn")+":"+r.PathValue("kind")]
	a.mu.Unlock()
	if !ok {
		write(w, 404, map[string]string{"error": "snapshot_not_found"})
		return
	}
	feed.DataMode = "demo"
	write(w, 200, feed)
}

func (a *API) put(w http.ResponseWriter, r *http.Request) {
	var feed obligations.Feed
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&feed) != nil || decoder.Decode(new(any)) != io.EOF || feed.CompanyINN != r.PathValue("inn") || feed.Validate(r.PathValue("kind")) != nil {
		write(w, 400, map[string]string{"error": "invalid_snapshot"})
		return
	}
	feed.DataMode = "demo"
	a.mu.Lock()
	defer a.mu.Unlock()
	next := make(map[string]obligations.Feed, len(a.feeds)+1)
	for k, v := range a.feeds {
		next[k] = v
	}
	next[feed.CompanyINN+":"+r.PathValue("kind")] = feed
	if e := a.save(next); e != nil {
		write(w, 500, map[string]string{"error": "storage_unavailable"})
		return
	}
	a.feeds = next
	write(w, 200, feed)
}

func (a *API) save(next map[string]obligations.Feed) error {
	file, e := os.CreateTemp(filepath.Dir(a.path), ".obligations-*")
	if e != nil {
		return e
	}
	name := file.Name()
	defer os.Remove(name)
	if e = json.NewEncoder(file).Encode(next); e != nil {
		file.Close()
		return e
	}
	if e = file.Sync(); e != nil {
		file.Close()
		return e
	}
	if e = file.Close(); e != nil {
		return e
	}
	return os.Rename(name, a.path)
}

func write(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}
