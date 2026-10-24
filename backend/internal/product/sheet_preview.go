package product

import (
	"context"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func (s *Service) SheetPreview(ctx context.Context, uid, id string, mapping Doc, confirm bool) (Result, error) {
	d, cfg, e := s.sourceConfig(ctx, uid, id)
	if e != nil {
		return Result{}, e
	}
	if text(d, "kind") != "gsheets" {
		return Result{}, bad("Это не источник Google Sheets")
	}
	if !flag(d, "enabled") {
		return Result{}, platform.Fail(409, "source_disabled", "Источник отключён")
	}
	data, e := s.fetchSheet(ctx, cfg)
	if e != nil {
		return Result{}, e
	}
	table, e := readTable(data, "csv")
	if e != nil {
		return Result{}, e
	}
	if !confirm {
		end := len(table)
		if end > 6 {
			end = 6
		}
		return ok(Doc{"source_id": id, "columns": table[0], "rows": table[1:end], "proposed_mapping": proposeMapping(table[0]), "data_mode": d["data_mode"]})
	}
	if e = fields(mapping, "date amount direction counterparty inn purpose balance id sign"); e != nil {
		return Result{}, e
	}
	if !mappingReady(mapping) {
		return Result{}, bad("Сопоставьте дату, сумму и направление")
	}
	for _, v := range mapping {
		column, ok := v.(string)
		if !ok {
			return Result{}, bad("Столбец должен быть строкой")
		}
		found := column == ""
		for _, name := range table[0] {
			found = found || name == column
		}
		if !found {
			return Result{}, bad("Столбец отсутствует в таблице")
		}
	}
	cfg["mapping"] = mapping
	sealed, e := s.seal(store.JSON(cfg))
	if e != nil {
		return Result{}, e
	}
	d["_sealed_config"], d["status"] = sealed, "pending"
	if _, e = s.DB.ProductSave(ctx, uid, text(d, "company_id"), "source", id, d, false); e != nil {
		return Result{}, e
	}
	return s.sourceAction(ctx, "syncSource", uid, id)
}
