package httpapi

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
)

func (s *Server) DiscoverOneCAccounting(ctx context.Context, r DiscoverOneCAccountingRequestObject) (DiscoverOneCAccountingResponseObject, error) {
	cfg := product.Doc{}
	for k, v := range rawBody(ctx) {
		var value any
		if e := json.Unmarshal(v, &value); e != nil {
			return nil, e
		}
		cfg[k] = value
	}
	out, e := s.Products.DiscoverOneC(ctx, principal(ctx).User.ID, r.CompanyId.String(), cfg)
	if e != nil {
		return nil, e
	}
	return reply{status: 200, data: out}, nil
}
func (a reply) VisitDiscoverOneCAccountingResponse(w http.ResponseWriter) error { return a.write(w) }
