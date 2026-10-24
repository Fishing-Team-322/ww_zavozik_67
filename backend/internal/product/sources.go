package product

import (
	"bytes"
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"encoding/csv"
	"encoding/json"
	"errors"
	"io"
	"math"
	"mime/multipart"
	"net/http"
	"net/url"
	"path"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/bridge"
	"github.com/google/uuid"
	"github.com/xuri/excelize/v2"
	"golang.org/x/text/encoding/charmap"
)

func (s *Service) seal(data []byte) ([]byte, error) {
	if len(s.EncryptionKey) != 32 {
		return nil, platform.Fail(503, "encryption_not_configured", "Для настроек источников нужен DATA_ENCRYPTION_KEY (32 байта в base64)")
	}
	block, e := aes.NewCipher(s.EncryptionKey)
	if e != nil {
		return nil, e
	}
	gcm, e := cipher.NewGCM(block)
	if e != nil {
		return nil, e
	}
	nonce := make([]byte, gcm.NonceSize())
	if _, e = rand.Read(nonce); e != nil {
		return nil, e
	}
	return gcm.Seal(nonce, nonce, data, []byte("zavozik-source-v1")), nil
}
func (s *Service) unseal(data []byte) (Doc, error) {
	if len(data) == 0 {
		return Doc{}, nil
	}
	if len(s.EncryptionKey) != 32 {
		return nil, platform.Fail(503, "encryption_not_configured", "Ключ настроек источников не настроен")
	}
	block, e := aes.NewCipher(s.EncryptionKey)
	if e != nil {
		return nil, e
	}
	gcm, e := cipher.NewGCM(block)
	if e != nil {
		return nil, e
	}
	if len(data) < gcm.NonceSize() {
		return nil, errors.New("invalid source secret")
	}
	plain, e := gcm.Open(nil, data[:gcm.NonceSize()], data[gcm.NonceSize():], []byte("zavozik-source-v1"))
	if e != nil {
		return nil, platform.Fail(503, "decryption_failed", "Не удалось открыть настройки источника")
	}
	return store.Decode(plain), nil
}
func (s *Service) validateSourceConfig(ctx context.Context, uid, cid, kind string, cfg Doc) error {
	switch kind {
	case "onec_odata":
		var c bridge.ODataConfig
		if e := json.Unmarshal(store.JSON(cfg), &c); e != nil {
			return bad("Некорректная настройка 1С")
		}
		company, e := s.DB.GetCompany(ctx, uid, cid)
		if e != nil {
			return e
		}
		if company.INN == nil {
			return bad("Сначала укажите ИНН компании")
		}
		c.CompanyID = cid
		c.CompanyINN = *company.INN
		cfg["company_id"], cfg["company_inn"] = cid, *company.INN
		if c.Validate() != nil {
			return bad("Проверьте base_url, company_account, account_map и коллекции 1С")
		}
		u, _ := url.Parse(c.BaseURL)
		allowed := false
		for _, host := range s.AllowedSourceHosts {
			if strings.EqualFold(u.Host, host) {
				allowed = true
			}
		}
		if !allowed {
			return platform.Fail(403, "source_host_not_allowed", "Адрес 1С должен быть разрешён администратором в SOURCE_ALLOWED_HOSTS")
		}
	case "gsheets":
		id := text(cfg, "spreadsheet_id")
		if id == "" || len(id) > 150 || strings.ContainsAny(id, "/\\?.#&") {
			return bad("Некорректный spreadsheet_id")
		}
		if len(text(cfg, "range")) > 300 {
			return bad("Слишком длинный диапазон")
		}
	case "fns":
		if len(cfg) > 0 {
			return bad("Ключ ФНС/DaData задаётся администратором в окружении")
		}
	}
	return nil
}
func (s *Service) sourceConfig(ctx context.Context, uid, id string) (Doc, Doc, error) {
	d, e := s.DB.ProductGet(ctx, uid, "source", id)
	if e != nil {
		return nil, nil, e
	}
	var sealed []byte
	if e = s.DB.Pool.QueryRow(ctx, "SELECT config_secret FROM sources WHERE id=$1", id).Scan(&sealed); e != nil {
		return nil, nil, e
	}
	cfg, e := s.unseal(sealed)
	return d, cfg, e
}
func (s *Service) sourceAction(ctx context.Context, op, uid, id string) (Result, error) {
	d, e := s.DB.ProductGet(ctx, uid, "source", id)
	if e != nil {
		return Result{}, e
	}
	cid := text(d, "company_id")
	if op == "getSource" {
		imports, e := s.DB.ProductList(ctx, uid, cid, "import")
		if e != nil {
			return Result{}, e
		}
		out := view("source", d)
		filtered := []Doc{}
		for _, v := range imports {
			if text(v, "source_id") == id {
				filtered = append(filtered, view("import", v))
			}
		}
		out["imports"] = filtered
		return ok(out)
	}
	if !flag(d, "enabled") {
		return Result{}, platform.Fail(409, "source_disabled", "Источник отключён")
	}
	kind := text(d, "kind")
	if !in(kind, "onec_odata gsheets fns") {
		if op == "testSource" {
			return ok(Doc{"ok": true, "message": "Файловый источник готов к загрузке"})
		}
		return Result{}, platform.Fail(409, "upload_required", "Для этого источника загрузите файл")
	}
	_, cfg, e := s.sourceConfig(ctx, uid, id)
	if e != nil {
		return Result{}, e
	}
	if e = s.validateSourceConfig(ctx, uid, cid, kind, cfg); e != nil {
		return Result{}, e
	}
	if op == "testSource" {
		switch kind {
		case "onec_odata":
			var c bridge.ODataConfig
			json.Unmarshal(store.JSON(cfg), &c)
			_, e = bridge.FetchOData(ctx, c, text(cfg, "username"), text(cfg, "password"))
		case "gsheets":
			_, e = s.fetchSheet(ctx, cfg)
		case "fns":
			company, err := s.DB.GetCompany(ctx, uid, cid)
			if err != nil {
				return Result{}, err
			}
			if company.INN == nil {
				return Result{}, bad("Укажите ИНН компании")
			}
			_, e = s.lookup(ctx, *company.INN)
		}
		if e != nil {
			var configured *platform.Error
			if errors.As(e, &configured) && configured.Status == 503 {
				return Result{}, e
			}
			return Result{}, platform.Fail(502, "source_test_failed", "Проверка источника не прошла. Проверьте доступ и настройки")
		}
		return ok(Doc{"ok": true, "message": "Соединение проверено"})
	}
	j, e := s.DB.ProductJob(ctx, uid, cid, "sync", Doc{"source_id": id})
	return Result{Status: 202, Body: j}, e
}
func (s *Service) deleteSource(ctx context.Context, uid, cid, id string, b Doc) (Result, error) {
	if e := fields(b, "keep_data"); e != nil {
		return Result{}, e
	}
	keep, yes := b["keep_data"].(bool)
	if !yes {
		return Result{}, bad("Укажите keep_data: true или false")
	}
	tx, e := s.DB.Pool.Begin(ctx)
	if e != nil {
		return Result{}, e
	}
	defer tx.Rollback(ctx)
	var locked string
	e = tx.QueryRow(ctx, "SELECT c.id::text FROM companies c JOIN memberships m ON m.company_id=c.id WHERE m.user_id=$1 AND c.id=$2 AND m.role='owner' FOR UPDATE OF c", uid, cid).Scan(&locked)
	if e != nil {
		return Result{}, platform.ErrNotFound
	}
	if !keep {
		if _, e = tx.Exec(ctx, "DELETE FROM operations WHERE source_id=$1 AND company_id=$2", id, cid); e != nil {
			return Result{}, e
		}
		if _, e = tx.Exec(ctx, "DELETE FROM planned_events WHERE source_id=$1 AND company_id=$2", id, cid); e != nil {
			return Result{}, e
		}
	}
	if _, e = tx.Exec(ctx, "DELETE FROM sources WHERE id=$1 AND company_id=$2", id, cid); e != nil {
		return Result{}, e
	}
	if _, e = tx.Exec(ctx, "UPDATE companies SET data_revision=data_revision+1 WHERE id=$1", cid); e != nil {
		return Result{}, e
	}
	if _, e = tx.Exec(ctx, `INSERT INTO product_jobs(actor_id,company_id,kind) VALUES($1,$2,'recompute') ON CONFLICT(company_id) WHERE kind='recompute' AND status='queued' DO NOTHING`, uid, cid); e != nil {
		return Result{}, e
	}
	if e = tx.Commit(ctx); e != nil {
		return Result{}, e
	}
	return Result{Status: 204}, nil
}
func (s *Service) lookup(ctx context.Context, inn string) (Result, error) {
	if len(inn) != 10 && len(inn) != 12 {
		return Result{}, bad("ИНН должен содержать 10 или 12 цифр")
	}
	for _, c := range inn {
		if c < '0' || c > '9' {
			return Result{}, bad("ИНН должен содержать цифры")
		}
	}
	if s.DaDataToken == "" {
		return Result{}, platform.Fail(503, "provider_not_configured", "Нужен ключ провайдера сведений об организациях DADATA_API_TOKEN")
	}
	party, e := bridge.Lookup(ctx, s.DaDataToken, inn, s.HTTP)
	if e != nil {
		return Result{}, platform.Fail(502, "registry_unavailable", "Реестр не ответил или организация не найдена")
	}
	var legal any
	if len(inn) == 12 {
		legal = "ИП"
	}
	return ok(Doc{"inn": party.INN, "name": party.Name, "legal_form": legal, "industry": nil, "tax_regime": "unknown", "status": party.Status, "source": party.SourceKind})
}
func (s *Service) upload(ctx context.Context, uid, cid string, reader *multipart.Reader) (Result, error) {
	if reader == nil {
		return Result{}, bad("Нужен multipart файл")
	}
	var data []byte
	filename := ""
	for {
		part, e := reader.NextPart()
		if e == io.EOF {
			break
		}
		if e != nil {
			return Result{}, bad("Некорректный multipart запрос")
		}
		if part.FormName() != "file" || part.FileName() == "" {
			part.Close()
			return Result{}, bad("Допускается только поле file")
		}
		if filename != "" {
			return Result{}, bad("Допускается ровно один файл")
		}
		filename = path.Base(strings.ReplaceAll(part.FileName(), "\\", "/"))
		data, e = io.ReadAll(io.LimitReader(part, 4*1024*1024+1))
		part.Close()
		if e != nil {
			return Result{}, bad("Не удалось прочитать файл")
		}
		if len(data) > 4*1024*1024 {
			return Result{}, platform.Fail(413, "upload_too_large", "Максимальный размер файла — 4 MiB")
		}
	}
	if len(data) == 0 {
		return Result{}, bad("Файл пуст")
	}
	data = bytes.TrimPrefix(data, []byte{0xef, 0xbb, 0xbf})
	format := "csv"
	if bytes.HasPrefix(data, []byte("1CClientBankExchange")) {
		format = "onec"
	} else if bytes.HasPrefix(data, []byte("PK\x03\x04")) {
		format = "xlsx"
	}
	id := uuid.NewString()
	var mapping Doc
	if format != "onec" {
		table, e := readTable(data, format)
		if e != nil {
			return Result{}, e
		}
		mapping = proposeMapping(table[0])
	}
	_, e := s.DB.Pool.Exec(ctx, "INSERT INTO product_uploads(id,company_id,filename,format,content,mapping) VALUES($1,$2,$3,$4,$5,$6)", id, cid, filename, format, data, string(store.JSON(mapping)))
	if e != nil {
		return Result{}, e
	}
	if format == "onec" || mappingReady(mapping) {
		j, e := s.DB.ProductJob(ctx, uid, cid, "import", Doc{"upload_id": id})
		return Result{Status: 202, Body: j}, e
	}
	return ok(Doc{"upload_id": id, "detected_format": format, "needs_mapping": true})
}
func readTable(data []byte, format string) ([][]string, error) {
	var table [][]string
	if format == "xlsx" {
		book, e := excelize.OpenReader(bytes.NewReader(data), excelize.Options{UnzipSizeLimit: 32 * 1024 * 1024, UnzipXMLSizeLimit: 8 * 1024 * 1024})
		if e != nil {
			return nil, bad("Не удалось прочитать XLSX")
		}
		defer book.Close()
		sheets := book.GetSheetList()
		if len(sheets) == 0 {
			return nil, bad("В книге нет листов")
		}
		rows, e := book.Rows(sheets[0])
		if e != nil {
			return nil, bad("Не удалось прочитать лист")
		}
		defer rows.Close()
		for rows.Next() {
			if len(table) >= 10001 {
				return nil, bad("Не более 10000 строк данных")
			}
			row, err := rows.Columns()
			if err != nil {
				return nil, bad("Не удалось прочитать строку XLSX")
			}
			table = append(table, row)
		}
		if rows.Error() != nil {
			return nil, bad("Не удалось прочитать лист")
		}
	} else {
		if !utf8.Valid(data) {
			var e error
			data, e = charmap.Windows1251.NewDecoder().Bytes(data)
			if e != nil {
				return nil, bad("Нужен текст UTF-8 или Windows-1251")
			}
		}
		data = bytes.TrimPrefix(data, []byte{0xef, 0xbb, 0xbf})
		if bytes.IndexByte(data, 0) >= 0 {
			return nil, bad("Некорректный CSV")
		}
		reader := csv.NewReader(bytes.NewReader(data))
		reader.FieldsPerRecord = -1
		first := strings.SplitN(string(data), "\n", 2)[0]
		if strings.Count(first, ";") > strings.Count(first, ",") {
			reader.Comma = ';'
		}
		if strings.Count(first, "\t") > strings.Count(first, string(reader.Comma)) {
			reader.Comma = '\t'
		}
		var e error
		table, e = reader.ReadAll()
		if e != nil {
			return nil, bad("Не удалось разобрать CSV")
		}
	}
	if len(table) < 2 || len(table) > 10001 || len(table[0]) == 0 || len(table[0]) > 100 {
		return nil, bad("Допускается заголовок и от 1 до 10000 строк, не более 100 столбцов")
	}
	for _, row := range table {
		if len(row) > 100 {
			return nil, bad("Слишком много столбцов")
		}
		for _, v := range row {
			if len(v) > 8192 {
				return nil, bad("Слишком длинная ячейка")
			}
		}
	}
	return table, nil
}
func proposeMapping(header []string) Doc {
	aliases := map[string]string{"date": "date", "дата": "date", "op_date": "date", "amount": "amount", "сумма": "amount", "direction": "direction", "направление": "direction", "counterparty": "counterparty", "counterparty_name": "counterparty", "контрагент": "counterparty", "inn": "inn", "counterparty_inn": "inn", "инн": "inn", "purpose": "purpose", "назначение": "purpose", "balance": "balance", "balance_eod": "balance", "остаток": "balance", "id": "id"}
	out := Doc{}
	for _, v := range header {
		if key, yes := aliases[strings.ToLower(strings.TrimSpace(v))]; yes {
			out[key] = v
		}
	}
	return out
}
func mappingReady(d Doc) bool {
	return text(d, "date") != "" && text(d, "amount") != "" && text(d, "direction") != ""
}
func (s *Service) uploadMapping(ctx context.Context, op, uid, id string, b Doc) (Result, error) {
	var cid, format string
	var data, raw []byte
	e := s.DB.Pool.QueryRow(ctx, `SELECT u.company_id::text,u.format,u.content,u.mapping FROM product_uploads u JOIN memberships m ON m.company_id=u.company_id WHERE u.id=$1 AND m.user_id=$2 AND m.role='owner'`, id, uid).Scan(&cid, &format, &data, &raw)
	if e != nil {
		return Result{}, platform.ErrNotFound
	}
	if format == "onec" {
		return Result{}, bad("Файл 1С не требует сопоставления")
	}
	table, e := readTable(data, format)
	if e != nil {
		return Result{}, e
	}
	if op == "previewUpload" {
		n := len(table)
		if n > 21 {
			n = 21
		}
		return ok(Doc{"columns": table[0], "rows": table[1:n], "proposed_mapping": store.Decode(raw)})
	}
	mapping, yes := b["mapping"].(map[string]any)
	if !yes {
		return Result{}, bad("Нужен объект mapping")
	}
	if e = fields(Doc(mapping), "date amount direction sign counterparty inn purpose balance id"); e != nil {
		return Result{}, e
	}
	if text(Doc(mapping), "date") == "" || text(Doc(mapping), "amount") == "" || text(Doc(mapping), "direction") == "" && text(Doc(mapping), "sign") == "" {
		return Result{}, bad("Нужны date, amount и direction либо sign")
	}
	headers := map[string]bool{}
	for _, name := range table[0] {
		headers[name] = true
	}
	for _, value := range mapping {
		col, yes := value.(string)
		if !yes || !headers[col] {
			return Result{}, bad("Сопоставление содержит неизвестный столбец")
		}
	}
	if _, e = s.DB.Pool.Exec(ctx, "UPDATE product_uploads SET mapping=$2 WHERE id=$1", id, string(store.JSON(mapping))); e != nil {
		return Result{}, e
	}
	j, e := s.DB.ProductJob(ctx, uid, cid, "import", Doc{"upload_id": id})
	return Result{Status: 202, Body: j}, e
}
func (s *Service) fetchSheet(ctx context.Context, cfg Doc) ([]byte, error) {
	rangeName := text(cfg, "range")
	if rangeName == "" {
		rangeName = "A1:Z10001"
	}
	address := "https://sheets.googleapis.com/v4/spreadsheets/" + url.PathEscape(text(cfg, "spreadsheet_id")) + "/values/" + url.PathEscape(rangeName)
	req, e := http.NewRequestWithContext(ctx, "GET", address, nil)
	if e != nil {
		return nil, e
	}
	if token := text(cfg, "access_token"); token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	if key := text(cfg, "api_key"); key != "" {
		req.Header.Set("X-Goog-Api-Key", key)
	}
	client := &http.Client{Timeout: 20 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	if s.HTTP != nil {
		client.Transport = s.HTTP.Transport
	}
	res, e := client.Do(req)
	if e != nil {
		return nil, platform.Fail(502, "sheet_unavailable", "Google Sheets недоступен")
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return nil, platform.Fail(502, "sheet_access_failed", "Проверьте доступ к Google Sheets и ключ")
	}
	data, e := io.ReadAll(io.LimitReader(res.Body, 4*1024*1024+1))
	if e != nil || len(data) > 4*1024*1024 {
		return nil, bad("Таблица слишком большая")
	}
	var payload struct {
		Values [][]string `json:"values"`
	}
	if e = json.Unmarshal(data, &payload); e != nil || len(payload.Values) < 2 {
		return nil, bad("Таблица пуста или имеет неизвестный формат")
	}
	buf := &bytes.Buffer{}
	writer := csv.NewWriter(buf)
	writer.WriteAll(payload.Values)
	if e = writer.Error(); e != nil {
		return nil, e
	}
	return buf.Bytes(), nil
}
func parseAmount(raw string) (float64, error) {
	raw = strings.ReplaceAll(strings.ReplaceAll(strings.TrimSpace(raw), " ", ""), "\u00a0", "")
	raw = strings.ReplaceAll(raw, ",", ".")
	v, e := strconv.ParseFloat(raw, 64)
	if e != nil || v != v || v > 1e13 || v < -1e13 || math.Abs(v*100-math.Round(v*100)) > .001 {
		return 0, bad("Некорректная сумма в строке")
	}
	return v, nil
}
