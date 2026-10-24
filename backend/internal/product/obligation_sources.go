package product

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/obligations"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

// A bank/accounting gateway exposes a complete snapshot of future obligations.
// Amounts are outstanding integer kopecks, never bank cash facts. The gateway
// authenticates the bank/accounting system; our bearer token is encrypted at rest.
type obligationFeed = obligations.Feed

func (s *Service) validateObligationSource(cfg Doc) error {
	if e := fields(cfg, "url token"); e != nil {
		return e
	}
	u, e := url.Parse(text(cfg, "url"))
	if e != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || u.Scheme != "https" && (u.Scheme != "http" || !isLoopbackHost(u.Hostname())) {
		return bad("Укажите HTTPS URL банковского/учётного шлюза или loopback URL для локального подключения")
	}
	allowed := false
	for _, host := range s.AllowedSourceHosts {
		allowed = allowed || strings.EqualFold(host, u.Host)
	}
	if !allowed {
		return platform.Fail(403, "source_host_not_allowed", "Адрес шлюза должен быть разрешён в SOURCE_ALLOWED_HOSTS")
	}
	if token := text(cfg, "token"); token == "" || len(token) > 8192 || strings.ContainsAny(token, "\r\n") {
		return bad("Укажите токен чтения шлюза")
	}
	return nil
}

func (s *Service) fetchObligations(ctx context.Context, uid, cid, kind string, cfg Doc) ([]Doc, string, error) {
	company, e := s.DB.GetCompany(ctx, uid, cid)
	if e != nil {
		return nil, "", e
	}
	if company.INN == nil {
		return nil, "", bad("Укажите ИНН компании для проверки принадлежности обязательств")
	}
	req, e := http.NewRequestWithContext(ctx, "GET", text(cfg, "url"), nil)
	if e != nil {
		return nil, "", bad("Некорректный URL шлюза")
	}
	req.Header.Set("Authorization", "Bearer "+text(cfg, "token"))
	req.Header.Set("Accept", "application/json")
	client := &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if s.HTTP != nil {
		client.Transport = s.HTTP.Transport
	}
	res, e := client.Do(req)
	if e != nil {
		return nil, "", platform.Fail(502, "obligation_source_unavailable", "Шлюз обязательств временно недоступен")
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return nil, "", platform.Fail(502, "obligation_source_unavailable", "Шлюз не подтвердил доступ к обязательствам")
	}
	raw, e := io.ReadAll(io.LimitReader(res.Body, (8<<20)+1))
	if e != nil || len(raw) > 8<<20 {
		return nil, "", platform.Fail(502, "invalid_obligation_feed", "Слишком большой или неполный ответ шлюза")
	}
	var feed obligationFeed
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.DisallowUnknownFields()
	if decoder.Decode(&feed) != nil || decoder.Decode(new(any)) != io.EOF || !feed.Complete || feed.Items == nil || len(feed.Items) > 10000 {
		return nil, "", platform.Fail(502, "invalid_obligation_feed", "Шлюз должен вернуть полный снимок обязательств по контракту")
	}
	if feed.CompanyINN != *company.INN {
		return nil, "", platform.Fail(502, "source_scope_mismatch", "Шлюз вернул обязательства другой компании")
	}
	feedKind := "bank"
	if kind == "tax_api" {
		feedKind = "tax"
	}
	if feed.Validate(feedKind) != nil {
		return nil, "", platform.Fail(502, "invalid_obligation_feed", "Некорректный снимок обязательств")
	}
	if feed.DataMode == "" {
		feed.DataMode = "unverified"
	}
	asOf, e := day(feed.AsOf)
	nowMSK := time.Now().In(time.FixedZone("MSK", 3*60*60))
	currentBusinessDate := time.Date(nowMSK.Year(), nowMSK.Month(), nowMSK.Day(), 0, 0, 0, 0, time.UTC)
	if e != nil || asOf.After(currentBusinessDate) {
		return nil, "", platform.Fail(502, "invalid_obligation_feed", "Некорректная дата снимка обязательств")
	}
	seen := map[string]bool{}
	events := []Doc{}
	for _, item := range feed.Items {
		if seen[item.ExternalID] || item.ExternalID == "" || len(item.ExternalID) > 200 || item.Title == "" || len([]rune(item.Title)) > 500 || item.AmountKopecks < 0 || item.AmountKopecks > 1_000_000_000_000_000 || !in(item.Status, "expected paid cancelled") || !in(item.Direction, "in out") || item.Status == "expected" && item.AmountKopecks == 0 {
			return nil, "", platform.Fail(502, "invalid_obligation_feed", "Некорректные реквизиты обязательства")
		}
		seen[item.ExternalID] = true
		if len(item.CounterpartyName) > 1024 || len(item.CounterpartyINN) > 12 {
			return nil, "", platform.Fail(502, "invalid_obligation_feed", "Некорректный контрагент обязательства")
		}
		category := "other"
		if kind == "bank_api" {
			if !in(item.Kind, "loan_payment salary payment_order") {
				return nil, "", platform.Fail(502, "invalid_obligation_feed", "Неизвестный вид банковского обязательства")
			}
			if item.Kind == "loan_payment" {
				category = "loan_payment"
			}
			if item.Kind == "salary" {
				category = "salary"
			}
		} else {
			if item.Kind != "tax" || item.Direction != "out" {
				return nil, "", platform.Fail(502, "invalid_obligation_feed", "Налоговый шлюз должен возвращать налоговые списания")
			}
			category = "tax"
		}
		var dates []time.Time
		if item.DueDate != "" {
			dt, err := day(item.DueDate)
			if err != nil {
				return nil, "", platform.Fail(502, "invalid_obligation_feed", "Некорректный срок обязательства")
			}
			dates = []time.Time{dt}
			if kind == "tax_api" {
				if item.TaxKind == "" {
					item.TaxKind = "other"
				}
				if item.Period == "" {
					item.Period = item.DueDate
				}
				if item.Year == 0 {
					item.Year = dt.Year()
				}
			}
		} else if kind == "tax_api" {
			var err error
			dates, _, err = taxDates(item.TaxKind, item.Period, company.LegalForm, "", item.Year)
			if err != nil {
				return nil, "", platform.Fail(502, "invalid_obligation_feed", "Не удалось определить налоговый срок; шлюз должен указать подтверждённую дату либо вид и период налога")
			}
		} else {
			return nil, "", platform.Fail(502, "invalid_obligation_feed", "Банк должен указать срок платежа")
		}
		if kind == "tax_api" && (!in(item.TaxKind, "usn_advance usn_annual vat enp contributions other") || item.Year < 2024 || item.Year > 2100 || item.Period == "") {
			return nil, "", platform.Fail(502, "invalid_obligation_feed", "Некорректный вид или период налогового обязательства")
		}
		digest := sha256.Sum256(store.JSON([]any{item, feed.DataMode, dates}))
		additional := true
		if item.Additional != nil {
			additional = *item.Additional
		}
		for i, dt := range dates {
			amount := item.AmountKopecks / int64(len(dates))
			if int64(i) < item.AmountKopecks%int64(len(dates)) {
				amount++
			}
			state := item.Status
			if state == "paid" {
				state = "received"
			}
			events = append(events, Doc{"external_id": item.ExternalID, "part": i, "event_date": dt.Format("2006-01-02"), "amount": float64(amount) / 100, "direction": item.Direction, "title": item.Title, "category": category, "status": state, "probability": 1, "counterparty_name": item.CounterpartyName, "counterparty_inn": item.CounterpartyINN, "additional": additional, "obligation_kind": item.Kind, "tax_kind": item.TaxKind, "period": item.Period, "year": item.Year, "source_url": text(cfg, "url"), "data_mode": feed.DataMode, "related_event_id": item.RelatedEventID, "document_number": item.DocumentNumber, "upstream_amount_kopecks": item.AmountKopecks, "upstream_hash": hex.EncodeToString(digest[:])})
		}
	}
	return events, feed.AsOf, nil
}

func (s *Service) syncObligations(ctx context.Context, j store.ProductJob, sourceID, kind string, cfg Doc) (Doc, error) {
	events, asOf, e := s.fetchObligations(ctx, j.UserID, j.CompanyID, kind, cfg)
	if e != nil {
		s.markSourceError(ctx, sourceID)
		return nil, e
	}
	tx, e := s.DB.Pool.Begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	var locked string
	if e = tx.QueryRow(ctx, "SELECT id::text FROM companies WHERE id=$1 FOR UPDATE", j.CompanyID).Scan(&locked); e != nil {
		return nil, e
	}
	var enabled bool
	var previousAsOf string
	if e = tx.QueryRow(ctx, "SELECT enabled,COALESCE(extra->>'feed_as_of','') FROM sources WHERE id=$1 AND company_id=$2 FOR UPDATE", sourceID, j.CompanyID).Scan(&enabled, &previousAsOf); e != nil {
		return nil, e
	}
	if !enabled {
		return nil, platform.Fail(409, "source_disabled", "Источник отключён")
	}
	if asOf < previousAsOf {
		return nil, platform.Fail(409, "stale_obligation_feed", "Шлюз вернул снимок старее сохранённого")
	}
	if kind == "tax_api" {
		previous, err := loadSourceEvents(ctx, tx, j.CompanyID, sourceID)
		if err != nil {
			return nil, err
		}
		if err = rebalanceTaxOutstanding(events, previous); err != nil {
			return nil, err
		}
	}
	ids := []string{}
	changed := 0
	for _, event := range events {
		id := idFor(j.CompanyID, fmt.Sprintf("obligation:%s:%s:%v", sourceID, text(event, "external_id"), event["part"]))
		ids = append(ids, id)
		preserveReceipt := flag(event, "preserve_receipt")
		delete(event, "preserve_receipt")
		if preserveReceipt {
			continue
		}
		tag, err := tx.Exec(ctx, `INSERT INTO planned_events(id,company_id,source_id,source_kind,event_date,amount,direction,title,category,counterparty_name,probability,status,extra)
VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,1,$11,$12)
ON CONFLICT(id) DO UPDATE SET event_date=EXCLUDED.event_date,amount=CASE WHEN EXCLUDED.status IN ('received','cancelled') AND EXCLUDED.amount=0 THEN planned_events.amount ELSE EXCLUDED.amount END,direction=EXCLUDED.direction,title=EXCLUDED.title,category=EXCLUDED.category,counterparty_name=EXCLUDED.counterparty_name,status=EXCLUDED.status,extra=EXCLUDED.extra
WHERE planned_events.matched_operation_id IS NULL AND (planned_events.extra->>'upstream_hash' IS DISTINCT FROM EXCLUDED.extra->>'upstream_hash' OR planned_events.status='cancelled' AND EXCLUDED.status='expected')`, id, j.CompanyID, sourceID, kind, event["event_date"], event["amount"], event["direction"], event["title"], event["category"], event["counterparty_name"], event["status"], store.JSON(event))
		if err != nil {
			return nil, err
		}
		changed += int(tag.RowsAffected())
	}
	// A receipt keeps its historical upstream_hash. Record the latest observed
	// snapshot separately so identical repeated feeds never repartition its debt.
	if kind == "tax_api" {
		seen := map[string]bool{}
		for _, event := range events {
			if seen[text(event, "external_id")] {
				continue
			}
			seen[text(event, "external_id")] = true
			if _, e = tx.Exec(ctx, `UPDATE planned_events SET extra=extra||jsonb_build_object('last_seen_upstream_hash',$4::text) WHERE company_id=$1 AND source_id=$2 AND extra->>'external_id'=$3 AND extra->>'last_seen_upstream_hash' IS DISTINCT FROM $4::text`, j.CompanyID, sourceID, text(event, "external_id"), text(event, "upstream_hash")); e != nil {
				return nil, e
			}
		}
	}
	// Omission in a complete snapshot cancels unpaid plans; paid history survives.
	tag, e := tx.Exec(ctx, "UPDATE planned_events SET status='cancelled' WHERE company_id=$1 AND source_id=$2 AND status IN ('expected','missed') AND matched_operation_id IS NULL AND NOT(id=ANY($3::uuid[]))", j.CompanyID, sourceID, ids)
	if e != nil {
		return nil, e
	}
	changed += int(tag.RowsAffected())
	if _, e = tx.Exec(ctx, "UPDATE sources SET last_synced_at=now(),status='ok',error=NULL,extra=extra||jsonb_build_object('feed_as_of',$3::text,'records',$4::int) WHERE id=$1 AND company_id=$2", sourceID, j.CompanyID, asOf, len(events)); e != nil {
		return nil, e
	}
	if len(events) > 0 {
		if _, e = tx.Exec(ctx, "UPDATE sources SET extra=extra||jsonb_build_object('data_mode',$2::text) WHERE id=$1", sourceID, text(events[0], "data_mode")); e != nil {
			return nil, e
		}
	}
	if changed > 0 {
		if _, e = tx.Exec(ctx, "UPDATE companies SET data_revision=data_revision+1 WHERE id=$1", j.CompanyID); e != nil {
			return nil, e
		}
		if _, e = tx.Exec(ctx, `INSERT INTO product_jobs(actor_id,company_id,kind) VALUES($1,$2,'recompute') ON CONFLICT(company_id) WHERE kind='recompute' AND status='queued' DO NOTHING`, j.UserID, j.CompanyID); e != nil {
			return nil, e
		}
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	return Doc{"plans_changed": changed, "bank_operations_added": 0, "result_ref": "/v1/companies/" + j.CompanyID + "/events"}, nil
}
