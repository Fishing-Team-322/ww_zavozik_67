package httpapi

import (
	"context"
	"net/http"
)

func (s *Server) ListMarketplaceReports(ctx context.Context, r ListMarketplaceReportsRequestObject) (ListMarketplaceReportsResponseObject, error) {
	rows, e := s.Products.DB.ProductList(ctx, principal(ctx).User.ID, r.CompanyId.String(), "marketplace_report")
	if e != nil {
		return nil, e
	}
	return reply{status: 200, data: rows}, nil
}
func (a reply) VisitListMarketplaceReportsResponse(w http.ResponseWriter) error { return a.write(w) }
