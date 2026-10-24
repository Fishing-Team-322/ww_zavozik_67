package service

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fns"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

type FNSSync struct {
	DB        *store.Postgres
	Client    *http.Client
	PageURL   string
	CompanyID string
	INNs      []string
}
type FNSSyncResult struct {
	Status      string          `json:"status"`
	Publication fns.Publication `json:"publication"`
	Summary     fns.Summary     `json:"summary"`
	Changed     int             `json:"changed"`
	Duplicates  int             `json:"duplicates"`
}

func (s FNSSync) Run(ctx context.Context) (result FNSSyncResult, err error) {
	if s.DB == nil || s.CompanyID == "" || len(s.INNs) == 0 {
		return result, errors.New("FNS sync is not configured")
	}
	page := s.PageURL
	if page == "" {
		page = fns.DatasetURL
	}
	client := s.Client
	if client == nil {
		client = &http.Client{Timeout: 5 * time.Minute, CheckRedirect: func(req *http.Request, _ []*http.Request) error {
			if req.URL.Scheme != "https" || (req.URL.Host != "www.nalog.gov.ru" && req.URL.Host != "file.nalog.ru") {
				return errors.New("unexpected FNS redirect")
			}
			return nil
		}}
	}
	release, locked, e := s.DB.TryDatasetLock(ctx, s.CompanyID)
	if e != nil {
		return result, e
	}
	if !locked {
		return result, errors.New("FNS sync already running")
	}
	defer release()
	status := "failed"
	code := "sync_failed"
	version := ""
	defer func() {
		c, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = s.DB.RecordDatasetRun(c, s.CompanyID, status, version, code)
	}()
	pub, e := fns.DiscoverDebt(ctx, client, page)
	if e != nil {
		code = "discovery_failed"
		return result, e
	}
	result.Publication = pub
	version = pub.Version
	old, e := s.DB.GetDatasetState(ctx, s.CompanyID)
	if e != nil {
		code = "state_read_failed"
		return result, e
	}
	if old.Publication.Version == pub.Version {
		status = "unchanged"
		code = ""
		result.Status = status
		result.Summary = fns.Summary{Files: old.Files, Documents: old.Documents, Matches: old.Matches}
		return result, nil
	}
	req, e := http.NewRequestWithContext(ctx, http.MethodGet, pub.URL, nil)
	if e != nil {
		return result, e
	}
	resp, e := client.Do(req)
	if e != nil {
		code = "download_failed"
		return result, e
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 || resp.ContentLength > 256<<20 {
		code = "download_failed"
		return result, errors.New("FNS archive unavailable or too large")
	}
	f, e := os.CreateTemp("", "fns-debt-*.zip")
	if e != nil {
		code = "temp_failed"
		return result, e
	}
	defer os.Remove(f.Name())
	defer f.Close()
	n, e := io.Copy(f, io.LimitReader(resp.Body, 256<<20+1))
	if e != nil || n > 256<<20 {
		code = "download_failed"
		return result, errors.New("FNS archive download failed or exceeded limit")
	}
	inns := make(map[string]struct{}, len(s.INNs))
	for _, inn := range s.INNs {
		inns[strings.TrimSpace(inn)] = struct{}{}
	}
	items, summary, e := fns.ParseArchive(ctx, f, n, inns, pub.URL, time.Now())
	if e != nil {
		code = "parse_failed"
		return result, e
	}
	result.Summary = summary
	signals := make([]store.RiskSignal, 0, len(items))
	for _, item := range items {
		sum := sha256.Sum256([]byte(item.DatasetAsOf + "\x00" + item.DocumentID + "\x00" + item.TaxName))
		signals = append(signals, store.RiskSignal{ExternalID: hex.EncodeToString(sum[:]), SourceKind: "fns_debt_snapshot", SubjectINN: item.INN, Kind: item.TaxName, AmountKopecks: item.AmountKopecks, DatasetAsOf: item.DatasetAsOf, PublishedAt: pub.PublishedAt, RetrievedAt: item.RetrievedAt, SourceURL: pub.URL, DataMode: "official_open_data"})
	}
	changed, duplicates, e := s.DB.SaveRisks(s.CompanyID, signals)
	if e != nil {
		code = "save_failed"
		return result, e
	}
	result.Changed = changed
	result.Duplicates = duplicates
	state := store.DatasetState{CompanyID: s.CompanyID, DatasetID: store.DebtDatasetID, Publication: pub, RetrievedAt: time.Now().UTC().Format(time.RFC3339), Files: summary.Files, Documents: summary.Documents, Matches: summary.Matches}
	if e = s.DB.SaveDatasetState(ctx, state); e != nil {
		code = "state_save_failed"
		return result, e
	}
	status = "updated"
	code = ""
	result.Status = status
	return result, nil
}
