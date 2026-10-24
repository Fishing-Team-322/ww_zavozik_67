package product

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/bridge"
)

func (s *Service) fetchMarketplace(ctx context.Context, kind string, cfg Doc) ([]Doc, error) {
	client := &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if s.HTTP != nil {
		client.Transport = s.HTTP.Transport
	}
	var raw []byte
	if kind == "wb" {
		entries, e := bridge.FetchWBMode(ctx, text(cfg, "api_key"), text(cfg, "from"), text(cfg, "to"), client, s.IntegrationSandbox)
		if e != nil {
			return nil, platform.Fail(502, "marketplace_unavailable", "Wildberries не подтвердил доступ к финансовому отчёту. Проверьте токен, права, период и лимиты сервиса.")
		}
		raw = store.JSON(entries)
	} else {
		from, _ := day(text(cfg, "from"))
		to, _ := day(text(cfg, "to"))
		entries, e := bridge.FetchOzon(ctx, text(cfg, "client_id"), text(cfg, "api_key"), from, to.Add(24*time.Hour-time.Second), client)
		if e != nil {
			return nil, platform.Fail(502, "marketplace_unavailable", "Ozon не подтвердил доступ к финансовому отчёту. Проверьте Client ID, API Key, права и период.")
		}
		raw = store.JSON(entries)
	}
	var rows []Doc
	if e := json.Unmarshal(raw, &rows); e != nil {
		return nil, e
	}
	for _, row := range rows {
		if s.IntegrationSandbox {
			row["data_mode"] = "mock"
		}
		row["period_from"], row["period_to"], row["forecast_eligible"], row["bank_fact"] = cfg["from"], cfg["to"], false, false
	}
	return rows, nil
}

func (s *Service) syncMarketplace(ctx context.Context, j store.ProductJob, sourceID, kind string, cfg Doc) (Doc, error) {
	rows, e := s.fetchMarketplace(ctx, kind, cfg)
	if e != nil {
		s.markSourceError(ctx, sourceID)
		return nil, e
	}
	tx, e := s.DB.Pool.Begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	// Serialize reports for this source, preserving prior versions by content digest.
	var enabled bool
	if e = tx.QueryRow(ctx, "SELECT enabled FROM sources WHERE id=$1 AND company_id=$2 FOR UPDATE", sourceID, j.CompanyID).Scan(&enabled); e != nil {
		return nil, e
	}
	if !enabled {
		return nil, platform.Fail(409, "source_disabled", "Источник отключён")
	}
	added, duplicates := 0, 0
	for _, row := range rows {
		digest := sha256.Sum256(store.JSON(row))
		row["content_sha256"] = hex.EncodeToString(digest[:])
		row["source_id"], row["provider"], row["retrieved_at"] = sourceID, kind, time.Now().UTC().Format(time.RFC3339)
		id := idFor(j.CompanyID, sourceID+":"+text(row, "external_id")+":"+hex.EncodeToString(digest[:]))
		tag, err := tx.Exec(ctx, "INSERT INTO product_documents(id,company_id,kind,data) VALUES($1,$2,'marketplace_report',$3) ON CONFLICT(id) DO NOTHING", id, j.CompanyID, store.JSON(row))
		if err != nil {
			return nil, err
		}
		if tag.RowsAffected() == 0 {
			duplicates++
		} else {
			added++
		}
	}
	_, e = tx.Exec(ctx, "UPDATE sources SET status='ok',error=NULL,last_synced_at=now(),extra=extra||jsonb_build_object('records',(SELECT count(*) FROM product_documents WHERE company_id=$2 AND kind='marketplace_report' AND data->>'source_id'=$1::text)) WHERE id=$1 AND company_id=$2", sourceID, j.CompanyID)
	if e != nil {
		return nil, e
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	return Doc{"reports_added": added, "reports_duplicates": duplicates, "bank_operations_added": 0, "forecast_eligible": false, "result_ref": "/v1/sources/" + sourceID}, nil
}
