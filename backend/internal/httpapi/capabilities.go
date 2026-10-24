package httpapi

import (
	"context"
	"net/http"
)

func (s *Server) GetIntegrationCapabilities(ctx context.Context, r GetIntegrationCapabilitiesRequestObject) (GetIntegrationCapabilitiesResponseObject, error) {
	if _, e := s.Products.DB.GetCompany(ctx, principal(ctx).User.ID, r.CompanyId.String()); e != nil {
		return nil, e
	}
	return reply{status: 200, data: map[string]any{"sandbox": s.Products.IntegrationSandbox, "dadata_configured": s.Products.DaDataToken != "", "fns_snapshot_configured": s.Products.FNSHubURL != "", "bank_pdf_supported": false, "registry_pdf_supported": true, "bank_obligations_api_supported": true, "tax_obligations_api_supported": true, "own_obligations_api_mode": "demo", "mode_notice": "Наличие адаптера не подтверждает подключение. Собственный банковский API работает в демонстрационном режиме. Обязательства являются планами; банковский факт подтверждается выпиской."}}, nil
}
func (a reply) VisitGetIntegrationCapabilitiesResponse(w http.ResponseWriter) error {
	return a.write(w)
}
