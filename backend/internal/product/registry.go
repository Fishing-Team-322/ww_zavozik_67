package product

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/bridge"
	"github.com/google/uuid"
)

func (s *Service) Registry(ctx context.Context, uid, cid, action string, r *http.Request) (Result, error) {
	company, err := s.DB.GetCompany(ctx, uid, cid)
	if err != nil {
		return Result{}, err
	}
	if action == "list" {
		rows, e := s.DB.ProductList(ctx, uid, cid, "registry")
		return Result{Status: 200, Body: rows}, e
	}
	if action == "preview" {
		r.Body = http.MaxBytesReader(nil, r.Body, (16<<20)+(64<<10))
		if e := r.ParseMultipartForm(1 << 20); e != nil {
			return Result{}, platform.Fail(413, "invalid_registry_upload", "Загрузите один PDF, XML или ZIP ФНС размером до 16 МиБ")
		}
		if r.MultipartForm != nil {
			defer r.MultipartForm.RemoveAll()
		}
		files := r.MultipartForm.File["file"]
		if len(files) != 1 || files[0].Size <= 0 || files[0].Size > 16<<20 {
			return Result{}, bad("Нужен один непустой документ ФНС до 16 МиБ")
		}
		file, e := files[0].Open()
		if e != nil {
			return Result{}, bad("Не удалось прочитать файл")
		}
		defer file.Close()
		data, e := io.ReadAll(io.LimitReader(file, (16<<20)+1))
		if e != nil || len(data) > 16<<20 {
			return Result{}, bad("Файл слишком большой")
		}
		records, e := bridge.ParseRegistry(ctx, data)
		if e != nil {
			message := "Не удалось распознать выписку ЕГРЮЛ/ЕГРИП. Нужен официальный PDF с текстовым слоем либо XML/ZIP ФНС. Банковские выписки загружаются отдельно."
			if strings.Contains(e.Error(), "OCR") {
				message = "В PDF нет текстового слоя. Скачайте официальную текстовую выписку ФНС: распознавание сканов пока не поддерживается."
			}
			return Result{}, platform.Fail(422, "invalid_registry_document", message)
		}
		hash := sha256.Sum256(data)
		preview := Doc{"records": records, "file_sha256": hex.EncodeToString(hash[:]), "expires_at": time.Now().UTC().Add(30 * time.Minute).Format(time.RFC3339), "signature_status": "NOT_VERIFIED"}
		saved, e := s.DB.ProductSave(ctx, uid, cid, "registry_preview", uuid.NewString(), preview, true)
		return Result{Status: 200, Body: saved}, e
	}
	if action == "confirm" {
		var input struct {
			PreviewID   string `json:"preview_id"`
			RecordIndex int    `json:"record_index"`
			Target      string `json:"target"`
		}
		dec := json.NewDecoder(r.Body)
		dec.DisallowUnknownFields()
		if e := dec.Decode(&input); e != nil {
			return Result{}, bad("Проверьте подтверждение документа")
		}
		if _, e := uuid.Parse(input.PreviewID); e != nil {
			return Result{}, bad("Некорректный предпросмотр")
		}
		preview, e := s.DB.ProductGet(ctx, uid, "registry_preview", input.PreviewID)
		if e != nil {
			return Result{}, e
		}
		if text(preview, "company_id") != cid {
			return Result{}, platform.ErrNotFound
		}
		expires, e := time.Parse(time.RFC3339, text(preview, "expires_at"))
		if e != nil || time.Now().After(expires) {
			return Result{}, platform.Fail(410, "preview_expired", "Предпросмотр устарел. Загрузите документ повторно.")
		}
		var records []bridge.RegistryRecord
		if e = json.Unmarshal(store.JSON(preview["records"]), &records); e != nil || input.RecordIndex < 0 || input.RecordIndex >= len(records) {
			return Result{}, bad("Выберите запись из документа")
		}
		record := records[input.RecordIndex]
		if input.Target != "company" && input.Target != "counterparty" {
			return Result{}, bad("Выберите: моя компания или контрагент")
		}
		if input.Target == "company" && (company.INN == nil || *company.INN != record.INN) {
			return Result{}, platform.Fail(409, "registry_inn_mismatch", "ИНН выписки не совпадает с ИНН рабочего пространства. Исправьте реквизиты своей компании или сохраните документ как контрагента.")
		}
		id := uuid.NewSHA1(uuid.MustParse(cid), []byte(text(preview, "file_sha256")+":"+record.INN+":"+fmt.Sprint(input.RecordIndex)+":"+input.Target)).String()
		doc := store.Decode(store.JSON(record))
		doc["target"], doc["file_sha256"], doc["ownership_verified"], doc["bank_account_verified"] = input.Target, text(preview, "file_sha256"), false, false
		doc["registry_matched"], doc["signature_status"] = true, "NOT_VERIFIED"
		saved, e := s.DB.ProductSave(ctx, uid, cid, "registry", id, doc, true)
		return Result{Status: 200, Body: saved}, e
	}
	return Result{}, platform.ErrNotFound
}
