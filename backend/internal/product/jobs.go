package product

import (
	"archive/zip"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/categorize"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/domain"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/ingest"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/bridge"
	"golang.org/x/text/encoding/charmap"
)

// ProcessOne claims a durable job with SKIP LOCKED. The bounded execution time
// is shorter than the reclaim lease; no detached per-request goroutines are used.
func (s *Service) ProcessOne(ctx context.Context) (bool, error) {
	if e := s.DB.ExpireProductJobs(ctx); e != nil {
		return false, e
	}
	j, e := s.DB.ClaimProductJob(ctx)
	if platform.IsStatus(e, 404) {
		return false, nil
	}
	if e != nil {
		return false, e
	}
	run, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	var result Doc
	if j.Kind != "retrain" {
		_, e = s.DB.GetCompany(run, j.UserID, j.CompanyID)
	}
	if e == nil {
		switch j.Kind {
		case "import":
			result, e = s.importJob(run, j)
		case "sync":
			result, e = s.syncJob(run, j)
		case "export":
			result, e = s.exportJob(run, j)
		case "recompute":
			var out Doc
			e = s.reconcileFacts(run, j.UserID, j.CompanyID)
			if e == nil {
				out, _, e = s.build(run, j.UserID, j.CompanyID, 30, "auto", nil, nil, true)
			}
			if e == nil {
				e = s.evaluateAlerts(run, j.UserID, j.CompanyID, out)
				result = Doc{"result_ref": "/v1/companies/" + j.CompanyID + "/forecast"}
			}
		case "retrain":
			result, e = s.trainJob(run, j)
		default:
			e = bad("Неизвестный вид задания")
		}
	}
	// Finalization uses the parent context, even when the bounded job timed out.
	finish, stop := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer stop()
	return true, s.DB.FinishProductJob(finish, j, result, e)
}
func (s *Service) Run(ctx context.Context) error {
	ticker := time.NewTicker(time.Second)
	defer ticker.Stop()
	for {
		if ctx.Err() != nil {
			return nil
		}
		worked, e := s.ProcessOne(ctx)
		if e != nil {
			return e
		}
		if worked {
			continue
		}
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}
	}
}
func (s *Service) importJob(ctx context.Context, j store.ProductJob) (Doc, error) {
	var format, cid string
	var data, mapping []byte
	e := s.DB.Pool.QueryRow(ctx, "SELECT company_id::text,format,content,mapping FROM product_uploads WHERE id=$1", text(j.Payload, "upload_id")).Scan(&cid, &format, &data, &mapping)
	if e != nil || cid != j.CompanyID {
		return nil, platform.ErrNotFound
	}
	sourceID := text(j.Payload, "source_id")
	if sourceID == "" {
		sourceID = idFor(cid, "upload:"+format)
	}
	var ops []domain.Operation
	var external map[string]string
	rejected := []Doc{}
	if format == "onec" {
		company, e := s.DB.GetCompany(ctx, j.UserID, cid)
		if e != nil {
			return nil, e
		}
		if company.INN == nil {
			return nil, bad("Для выписки 1С укажите ИНН компании")
		}
		account := ""
		header := data
		if !utf8.Valid(header) {
			header, e = charmap.Windows1251.NewDecoder().Bytes(header)
			if e != nil {
				return nil, bad("Неизвестная кодировка выписки 1С")
			}
		}
		for _, line := range strings.Split(string(header), "\n") {
			line = strings.TrimSpace(line)
			if strings.HasPrefix(line, "РасчСчет=") {
				account = strings.TrimPrefix(line, "РасчСчет=")
				break
			}
		}
		batch, e := bridge.ParseBank(ctx, bytes.NewReader(data), bridge.Identity{CompanyID: cid, CompanyINN: *company.INN, CompanyAccount: account})
		if e != nil {
			return nil, bad("Не удалось разобрать выписку 1С: проверьте ИНН и счёт")
		}
		ops, external, e = batchOperations(batch)
		if e != nil {
			return nil, e
		}
		for _, issue := range batch.Issues {
			rejected = append(rejected, Doc{"row": issue.Section, "code": issue.Code, "message": issue.Message})
		}
	} else {
		table, e := readTable(data, format)
		if e != nil {
			return nil, e
		}
		ops, external, rejected = tableOperations(cid, table, store.Decode(mapping))
	}
	return s.saveImport(ctx, j, sourceID, format, ops, external, rejected, nil)
}
func batchOperations(batch bridge.Batch) ([]domain.Operation, map[string]string, error) {
	out := []domain.Operation{}
	keys := map[string]string{}
	for _, d := range batch.Operations {
		if !d.Executed {
			continue
		}
		dt, e := day(d.Date)
		if e != nil {
			return nil, nil, e
		}
		if d.AmountKopecks < 0 || d.AmountKopecks > 1000000000000000 {
			return nil, nil, bad("Сумма за пределами поддерживаемого диапазона")
		}
		id := idFor(batch.CompanyID, batch.SourceKind+":"+d.DedupKey)
		op := domain.Operation{ID: id, CompanyID: batch.CompanyID, Date: dt, Amount: domain.Money(float64(d.AmountKopecks) / 100), Direction: domain.Direction(d.Direction), CounterpartyName: domain.Name(d.CounterpartyName), CounterpartyINN: domain.INN(d.CounterpartyINN), Purpose: domain.Purpose(d.Purpose), Source: domain.SourceKind(batch.SourceKind), DedupHash: d.DedupKey}
		if d.BalanceEODKopecks != nil {
			v := domain.Money(float64(*d.BalanceEODKopecks) / 100)
			op.BalanceEOD = &v
		}
		out = append(out, op)
		keys[id] = d.DedupKey
	}
	return out, keys, nil
}
func tableOperations(cid string, table [][]string, mapping Doc) ([]domain.Operation, map[string]string, []Doc) {
	index := map[string]int{}
	for i, h := range table[0] {
		index[h] = i
	}
	cell := func(row []string, key string) string {
		i, ok := index[text(mapping, key)]
		if !ok || i >= len(row) {
			return ""
		}
		return strings.TrimSpace(row[i])
	}
	out := []domain.Operation{}
	keys := map[string]string{}
	issues := []Doc{}
	occurrences := map[string]int{}
	for i, row := range table[1:] {
		dt := cell(row, "date")
		if parsed, e := time.Parse("02.01.2006", dt); e == nil {
			dt = parsed.Format(domain.DateLayout)
		}
		dateValue, e1 := day(dt)
		amount, e2 := parseAmount(cell(row, "amount"))
		direction := strings.ToLower(cell(row, "direction"))
		switch direction {
		case "приход", "поступление", "income", "+":
			direction = "in"
		case "расход", "списание", "expense", "-":
			direction = "out"
		}
		if text(mapping, "sign") != "" {
			sign := strings.ToLower(cell(row, "sign"))
			if in(sign, "- out расход списание") || amount < 0 {
				direction = "out"
			} else {
				direction = "in"
			}
		}
		if amount < 0 {
			amount = -amount
		}
		if e1 != nil || e2 != nil || !in(direction, "in out") || dateValue.After(today()) || dateValue.Before(time.Date(2000, 1, 1, 0, 0, 0, 0, time.UTC)) {
			issues = append(issues, Doc{"row": i + 2, "code": "invalid_operation", "message": "Проверьте дату, сумму и направление"})
			continue
		}
		canonical := dt + "|" + cell(row, "amount") + "|" + direction + "|" + cell(row, "counterparty") + "|" + cell(row, "inn") + "|" + cell(row, "purpose")
		if original := cell(row, "id"); original != "" {
			canonical = "id:" + original
		} else {
			occurrences[canonical]++
			canonical += "|occurrence:" + strconvItoa(occurrences[canonical])
		}
		sum := sha256.Sum256([]byte(canonical))
		key := hex.EncodeToString(sum[:])
		id := idFor(cid, "csv:"+key)
		op := domain.Operation{ID: id, CompanyID: cid, Date: dateValue, Amount: domain.Money(amount), Direction: domain.Direction(direction), CounterpartyName: domain.Name(cell(row, "counterparty")), CounterpartyINN: domain.INN(cell(row, "inn")), Purpose: domain.Purpose(cell(row, "purpose")), DedupHash: key, Source: domain.SrcUpload}
		if raw := cell(row, "balance"); raw != "" {
			balance, e := parseAmount(raw)
			if e != nil {
				issues = append(issues, Doc{"row": i + 2, "code": "invalid_balance", "message": "Проверьте остаток"})
				continue
			}
			v := domain.Money(balance)
			op.BalanceEOD = &v
		}
		out = append(out, op)
		keys[id] = key
	}
	return out, keys, issues
}
func (s *Service) saveImport(ctx context.Context, j store.ProductJob, sourceID, kind string, ops []domain.Operation, keys map[string]string, issues []Doc, plans []bridge.PlannedEvent) (Doc, error) {
	clean, quality := ingest.Deduplicate(ops)
	cat := s.Categorizer
	if cat == nil {
		cat = categorize.DefaultRules
	}
	classified, e := cat.Categorize(ctx, clean)
	if e != nil {
		return nil, platform.Fail(502, "categorization_failed", "Не удалось определить категории")
	}
	categorize.Apply(clean, classified)
	for i := range clean {
		if clean[i].Category == domain.CatUnknown {
			clean[i].Category = domain.CatOther
			clean[i].CategoryMethod = domain.MethodRule
		}
	}
	ruleRows, e := s.DB.Pool.Query(ctx, "SELECT counterparty_key,category FROM category_rules WHERE company_id=$1", j.CompanyID)
	if e != nil {
		return nil, e
	}
	rules := map[string]string{}
	for ruleRows.Next() {
		var k, v string
		if e = ruleRows.Scan(&k, &v); e != nil {
			ruleRows.Close()
			return nil, e
		}
		rules[k] = v
	}
	e = ruleRows.Err()
	ruleRows.Close()
	if e != nil {
		return nil, e
	}
	tx, e := s.DB.Pool.Begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(ctx)
	var owned bool
	if e = tx.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM memberships WHERE user_id=$1 AND company_id=$2 AND role='owner')", j.UserID, j.CompanyID).Scan(&owned); e != nil {
		return nil, e
	}
	if !owned {
		return nil, platform.ErrNotFound
	}
	var rev int64
	if e = tx.QueryRow(ctx, "SELECT data_revision FROM companies WHERE id=$1 FOR UPDATE", j.CompanyID).Scan(&rev); e != nil {
		return nil, e
	}
	sourceKind := kind
	if kind == "onec" {
		sourceKind = "onec_bank_file"
	}
	if kind == "csv" {
		sourceKind = "upload"
	}
	_, e = tx.Exec(ctx, "INSERT INTO sources(id,company_id,kind,title) VALUES($1,$2,$3,$4) ON CONFLICT(id) DO NOTHING", sourceID, j.CompanyID, sourceKind, "Загрузка "+sourceKind)
	if e != nil {
		return nil, e
	}
	added, duplicates := 0, quality.Removed
	for _, op := range clean {
		key := cpKey(Doc{"counterparty_inn": string(op.CounterpartyINN), "counterparty_name": string(op.CounterpartyName)})
		if rule, yes := rules[key]; yes {
			op.Category = domain.Category(rule)
			op.CategoryMethod = domain.MethodUser
		}
		var bal any
		if op.BalanceEOD != nil {
			bal = op.BalanceEOD.Float()
		}
		tag, e := tx.Exec(ctx, `INSERT INTO operations(id,company_id,source_id,op_date,amount,direction,counterparty_inn,counterparty_name,purpose,balance_eod,category,category_method,is_internal,dedup_hash,extra)
 VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15) ON CONFLICT(company_id,id) DO NOTHING`, op.ID, j.CompanyID, sourceID, op.Date, op.Amount.Float(), string(op.Direction), string(op.CounterpartyINN), string(op.CounterpartyName), string(op.Purpose), bal, string(op.Category), string(op.CategoryMethod), op.Category.IsInternal(), keys[op.ID], string(store.JSON(Doc{"source": sourceKind})))
		if e != nil {
			return nil, e
		}
		if tag.RowsAffected() == 0 {
			duplicates++
		} else {
			added++
		}
	}
	planCounts, e := saveOneCPlans(ctx, tx, j.CompanyID, sourceID, plans)
	if e != nil {
		return nil, e
	}
	importID := idFor(j.CompanyID, "import-job:"+j.ID)
	report := Doc{"id": importID, "source_id": sourceID, "source": Doc{"id": sourceID, "kind": sourceKind}, "started_at": time.Now().UTC().Format(time.RFC3339), "added": added, "duplicates": duplicates, "plans_added": planCounts.Added, "plans_updated": planCounts.Updated, "plans_duplicates": planCounts.Duplicates, "duplicate_candidates_retained": quality.Unconfirmed, "gaps": []Doc{}, "errors": issues, "status": "done"}
	if len(clean) > 0 {
		ingest.SortOps(clean)
		report["period"] = Doc{"from": clean[0].Date.Format(domain.DateLayout), "to": clean[len(clean)-1].Date.Format(domain.DateLayout)}
	}
	if _, e = tx.Exec(ctx, "INSERT INTO product_documents(id,company_id,kind,data) VALUES($1,$2,'import',$3) ON CONFLICT(id) DO NOTHING", importID, j.CompanyID, string(store.JSON(report))); e != nil {
		return nil, e
	}
	if _, e = tx.Exec(ctx, "UPDATE sources SET status='ok',error=NULL,last_synced_at=now(),extra=extra||jsonb_build_object('records',(SELECT count(*) FROM operations WHERE source_id=$1)) WHERE id=$1 AND company_id=$2", sourceID, j.CompanyID); e != nil {
		return nil, e
	}
	if _, e = tx.Exec(ctx, "UPDATE companies SET data_revision=data_revision+1,updated_at=now() WHERE id=$1", j.CompanyID); e != nil {
		return nil, e
	}
	if _, e = tx.Exec(ctx, `INSERT INTO product_jobs(actor_id,company_id,kind) VALUES($1,$2,'recompute') ON CONFLICT(company_id) WHERE kind='recompute' AND status='queued' DO NOTHING`, j.UserID, j.CompanyID); e != nil {
		return nil, e
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	if e = s.detectRecurring(ctx, j.UserID, j.CompanyID); e != nil {
		return nil, e
	}
	if e = s.evaluateSignals(ctx, j.UserID, j.CompanyID); e != nil {
		return nil, e
	}
	return Doc{"result_ref": "/v1/imports/" + importID, "added": added, "duplicates": duplicates, "plans_added": planCounts.Added, "plans_updated": planCounts.Updated, "plans_duplicates": planCounts.Duplicates, "errors": len(issues)}, nil
}
func (s *Service) syncJob(ctx context.Context, j store.ProductJob) (Doc, error) {
	id := text(j.Payload, "source_id")
	source, cfg, e := s.sourceConfig(ctx, j.UserID, id)
	if e != nil {
		return nil, e
	}
	if text(source, "company_id") != j.CompanyID {
		return nil, platform.ErrNotFound
	}
	if !flag(source, "enabled") {
		return nil, platform.Fail(409, "source_disabled", "Источник отключён")
	}
	kind := text(source, "kind")
	if e = s.validateSourceConfig(ctx, j.UserID, j.CompanyID, kind, cfg, true); e != nil {
		return nil, e
	}
	if kind == "onec_odata" {
		var c bridge.ODataConfig
		json.Unmarshal(store.JSON(cfg), &c)
		batch, err := bridge.FetchOData(ctx, c, text(cfg, "username"), text(cfg, "password"))
		if err != nil {
			s.markSourceError(ctx, id)
			return nil, platform.Fail(502, "source_sync_failed", "Не удалось прочитать 1С")
		}
		if batch.CompanyID != j.CompanyID {
			return nil, platform.Fail(502, "source_scope_mismatch", "Источник вернул данные другой компании")
		}
		plans := []bridge.PlannedEvent{}
		if raw, ok := cfg["plan_config"]; ok {
			var planConfig bridge.ODataPlanConfig
			if err := json.Unmarshal(store.JSON(raw), &planConfig); err != nil {
				return nil, bad("Некорректная настройка обязательств 1С")
			}
			planConfig.CompanyID = j.CompanyID
			planConfig.BaseURL = c.BaseURL
			if planConfig.Validate() != nil {
				return nil, bad("Проверьте коллекции и поля обязательств 1С")
			}
			planBatch, err := bridge.FetchODataPlans(ctx, planConfig, text(cfg, "username"), text(cfg, "password"))
			if err != nil {
				s.markSourceError(ctx, id)
				return nil, platform.Fail(502, "source_plan_sync_failed", "Не удалось прочитать обязательства 1С")
			}
			if planBatch.CompanyID != j.CompanyID {
				return nil, platform.Fail(502, "source_scope_mismatch", "Источник вернул данные другой компании")
			}
			plans = planBatch.PlannedEvents
		}
		ops, keys, err := batchOperations(batch)
		if err != nil {
			return nil, err
		}
		return s.saveImport(ctx, j, id, kind, ops, keys, []Doc{}, plans)
	}
	if kind == "gsheets" {
		data, err := s.fetchSheet(ctx, cfg)
		if err != nil {
			s.markSourceError(ctx, id)
			return nil, err
		}
		table, err := readTable(data, "csv")
		if err != nil {
			return nil, err
		}
		mapping := proposeMapping(table[0])
		if custom, yes := cfg["mapping"].(map[string]any); yes {
			mapping = Doc(custom)
		}
		if !mappingReady(mapping) {
			return nil, bad("Настройте mapping столбцов Google Sheets")
		}
		ops, keys, issues := tableOperations(j.CompanyID, table, mapping)
		return s.saveImport(ctx, j, id, kind, ops, keys, issues, nil)
	}
	if kind == "fns" {
		company, err := s.DB.GetCompany(ctx, j.UserID, j.CompanyID)
		if err != nil {
			return nil, err
		}
		if company.INN == nil {
			return nil, bad("Укажите ИНН компании")
		}
		result, err := s.lookup(ctx, j.UserID, *company.INN)
		if err != nil {
			return nil, err
		}
		_, err = s.DB.Pool.Exec(ctx, "UPDATE sources SET last_synced_at=now(),status='ok',error=NULL WHERE id=$1", id)
		if err != nil {
			return nil, err
		}
		return Doc{"result_ref": "/v1/sources/" + id, "registry": result.Body}, nil
	}
	return nil, bad("Источник не поддерживает синхронизацию")
}
func (s *Service) markSourceError(ctx context.Context, id string) {
	_, _ = s.DB.Pool.Exec(ctx, "UPDATE sources SET status='error',error='Не удалось синхронизировать источник' WHERE id=$1", id)
}
func (s *Service) exportJob(ctx context.Context, j store.ProductJob) (Doc, error) {
	buf := &bytes.Buffer{}
	writer := zip.NewWriter(buf)
	company, e := s.DB.GetCompany(ctx, j.UserID, j.CompanyID)
	if e != nil {
		return nil, e
	}
	file, e := writer.Create("company.json")
	if e != nil {
		return nil, e
	}
	if _, e = file.Write(store.JSON(company)); e != nil {
		return nil, e
	}
	for _, kind := range []string{"operation", "event", "recurring", "scenario", "invoice", "contract", "source", "alert"} {
		rows, e := s.DB.ProductList(ctx, j.UserID, j.CompanyID, kind)
		if e != nil {
			return nil, e
		}
		out := []Doc{}
		for _, d := range rows {
			out = append(out, view(kind, d))
		}
		f, e := writer.Create(kind + "s.json")
		if e != nil {
			return nil, e
		}
		if _, e = f.Write(store.JSON(out)); e != nil {
			return nil, e
		}
	}
	var forecasts []byte
	if e = s.DB.Pool.QueryRow(ctx, "SELECT COALESCE(jsonb_agg(payload),'[]') FROM forecast_runs WHERE company_id=$1", j.CompanyID).Scan(&forecasts); e != nil {
		return nil, e
	}
	file, e = writer.Create("forecasts.json")
	if e != nil {
		return nil, e
	}
	if _, e = file.Write(forecasts); e != nil {
		return nil, e
	}
	if e = writer.Close(); e != nil {
		return nil, e
	}
	if _, e = s.DB.Pool.Exec(ctx, "INSERT INTO product_downloads(job_id,filename,mime,content) VALUES($1,'company-export.zip','application/zip',$2) ON CONFLICT(job_id) DO UPDATE SET content=EXCLUDED.content", j.ID, buf.Bytes()); e != nil {
		return nil, e
	}
	return Doc{"result_ref": "/v1/jobs/" + j.ID + "/download"}, nil
}
func (s *Service) download(ctx context.Context, uid, id string) (Result, error) {
	if _, e := s.DB.GetProductJob(ctx, uid, id, false); e != nil {
		return Result{}, e
	}
	var out Result
	out.Status = 200
	e := s.DB.Pool.QueryRow(ctx, "SELECT filename,mime,content FROM product_downloads WHERE job_id=$1", id).Scan(&out.Filename, &out.MIME, &out.Data)
	if e != nil {
		return Result{}, platform.ErrNotFound
	}
	return out, nil
}
func (s *Service) trainJob(ctx context.Context, j store.ProductJob) (Doc, error) {
	if s.TrainingURL == "" {
		return nil, platform.Fail(503, "training_not_configured", "Сервис переобучения не настроен")
	}
	req, e := http.NewRequestWithContext(ctx, "POST", s.TrainingURL, bytes.NewReader(store.JSON(Doc{"model": text(j.Payload, "model")})))
	if e != nil {
		return nil, e
	}
	req.Header.Set("Content-Type", "application/json")
	if s.TrainingToken != "" {
		req.Header.Set("Authorization", "Bearer "+s.TrainingToken)
	}
	client := &http.Client{Timeout: 110 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if s.HTTP != nil {
		client.Transport = s.HTTP.Transport
	}
	res, e := client.Do(req)
	if e != nil {
		return nil, platform.Fail(502, "training_failed", "Сервис переобучения не ответил")
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return nil, platform.Fail(502, "training_failed", "Сервис не подтвердил завершение переобучения")
	}
	var result Doc
	if e = json.NewDecoder(io.LimitReader(res.Body, 64*1024)).Decode(&result); e != nil || !flag(result, "trained") || text(result, "model_version") == "" {
		return nil, platform.Fail(502, "training_unconfirmed", "Сервис не вернул версию обученного артефакта")
	}
	return Doc{"model": text(j.Payload, "model"), "model_version": text(result, "model_version"), "result_ref": "/v1/admin/models"}, nil
}
func (s *Service) evaluateAlerts(ctx context.Context, uid, cid string, out Doc) error {
	for _, gap := range docs(out["gaps"]) {
		id := idFor(cid, "alert:"+text(gap, "id"))
		if _, e := s.DB.ProductGet(ctx, uid, "alert", id); e == nil {
			continue
		}
		d := Doc{"id": id, "severity": "warning", "title": "Возможен недостаток денег", "body": "Проверьте прогноз и ближайшие платежи", "kind": "gap_risk", "read": false, "ref": Doc{"screen": "gap", "id": gap["id"]}}
		if _, e := s.DB.ProductSave(ctx, uid, cid, "alert", id, d, true); e != nil {
			return e
		}
	}
	return nil
}
func strconvItoa(n int) string {
	const digits = "0123456789"
	if n == 0 {
		return "0"
	}
	var b [24]byte
	i := len(b)
	for n > 0 {
		i--
		b[i] = digits[n%10]
		n /= 10
	}
	return string(b[i:])
}
