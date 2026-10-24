package httpapi

import (
	"context"
	"net/http"
)

func (s *Server) GetFNSOpenData(ctx context.Context, r GetFNSOpenDataRequestObject) (GetFNSOpenDataResponseObject, error) {
	out, e := s.Products.FNSSnapshot(ctx, principal(ctx).User.ID, r.CompanyId.String())
	if e != nil {
		return nil, e
	}
	return reply{status: 200, data: out}, nil
}
func (a reply) VisitGetFNSOpenDataResponse(w http.ResponseWriter) error { return a.write(w) }
