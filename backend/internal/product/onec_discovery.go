package product

import (
	"context"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/bridge"
)

func (s *Service) DiscoverOneC(ctx context.Context, uid, cid string, cfg Doc) (Doc, error) {
	if e := fields(cfg, "base_url username password"); e != nil {
		return nil, e
	}
	if e := s.validateSourceConfig(ctx, uid, cid, "onec_odata", cfg, false); e != nil {
		return nil, e
	}
	company, e := s.DB.GetCompany(ctx, uid, cid)
	if e != nil {
		return nil, e
	}
	orgs, e := bridge.DiscoverAccounting(ctx, text(cfg, "base_url"), *company.INN, text(cfg, "username"), text(cfg, "password"))
	if e != nil {
		return nil, platform.Fail(422, "onec_discovery_failed", "Не удалось прочитать организации и счета. Проверьте публикацию справочников, адрес и учётную запись с правом чтения.")
	}
	if len(orgs) == 0 {
		return nil, platform.Fail(422, "onec_organization_missing", "В опубликованной базе не найдена организация с ИНН этого рабочего пространства. Создание профиля ПУЛЬС не создаёт организацию в 1С.")
	}
	return Doc{"organizations": orgs}, nil
}
