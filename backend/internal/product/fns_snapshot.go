package product

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
)

func (s *Service) FNSSnapshot(ctx context.Context, uid, cid string) (Doc, error) {
	company, e := s.DB.GetCompany(ctx, uid, cid)
	if e != nil {
		return nil, e
	}
	result := Doc{"configured": false, "status": "not_configured", "signals": []Doc{}, "publication": nil, "last_sync": nil, "bank_fact": false, "interpretation": "Публикация ФНС о задолженности — датированный риск-сигнал, не текущий баланс ЕНС и не платёж. Отсутствие записи не доказывает отсутствие долга."}
	if s.FNSHubURL == "" || s.FNSHubToken == "" || s.FNSHubCompany == "" {
		return result, nil
	}
	allowed := map[string]bool{}
	if company.INN != nil {
		allowed[*company.INN] = true
	}
	records, e := s.DB.ProductList(ctx, uid, cid, "registry")
	if e != nil {
		return nil, e
	}
	for _, r := range records {
		allowed[text(r, "inn")] = true
	}
	client := &http.Client{Timeout: 20 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if s.HTTP != nil && !s.IntegrationSandbox {
		client.Transport = s.HTTP.Transport
	}
	fetch := func(path string) (Doc, error) {
		req, err := http.NewRequestWithContext(ctx, "GET", strings.TrimRight(s.FNSHubURL, "/")+path, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("Authorization", "Bearer "+s.FNSHubToken)
		resp, err := client.Do(req)
		if err != nil {
			return nil, platform.Fail(502, "fns_snapshot_unavailable", "Снимок ФНС временно недоступен. Повторите позже.")
		}
		defer resp.Body.Close()
		if resp.StatusCode != 200 {
			return nil, platform.Fail(502, "fns_snapshot_unavailable", "Снимок ФНС временно недоступен. Повторите позже.")
		}
		var d Doc
		if err = json.NewDecoder(io.LimitReader(resp.Body, 8<<20)).Decode(&d); err != nil {
			return nil, platform.Fail(502, "fns_snapshot_invalid", "Не удалось прочитать опубликованный снимок ФНС")
		}
		return d, nil
	}
	state, e := fetch("/v1/fns/opendata/status")
	if e != nil {
		return nil, e
	}
	result["auto_refresh_configured"] = state["configured"] == true
	data, e := fetch("/v1/risk-signals/" + url.PathEscape(s.FNSHubCompany))
	if e != nil {
		return nil, e
	}
	signals := []Doc{}
	for _, r := range docs(data["risk_signals"]) {
		if allowed[text(r, "subject_inn")] {
			signals = append(signals, r)
		}
	}
	result["configured"], result["status"], result["signals"] = true, "no_snapshot", signals
	if success, ok := state["last_success"].(map[string]any); ok {
		result["publication"], result["last_sync"] = success["publication"], success["retrieved_at"]
		if text(Doc(success), "retrieved_at") != "" {
			result["status"] = "snapshot_available"
		}
		if text(Doc(success), "retrieved_at") == "" {
			result["status"] = "no_snapshot"
		}
	}
	// Only expose synchronization outcome, never Hub tenant IDs or unrelated subjects.
	runs := docs(state["runs"])
	if len(runs) > 0 {
		run := runs[0]
		result["last_run"] = Doc{"status": run["status"], "started_at": run["started_at"], "finished_at": run["finished_at"]}
	}
	return result, nil
}
