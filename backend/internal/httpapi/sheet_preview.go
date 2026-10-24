package httpapi

import (
	"context"
	"encoding/json"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"net/http"
)

func (s *Server) PreviewSheetSource(ctx context.Context, r PreviewSheetSourceRequestObject) (PreviewSheetSourceResponseObject, error) {
	out, e := s.Products.SheetPreview(ctx, principal(ctx).User.ID, r.SourceId.String(), nil, false)
	if e != nil {
		return nil, e
	}
	return reply{status: out.Status, data: out.Body}, nil
}
func (s *Server) ConfirmSheetMapping(ctx context.Context, r ConfirmSheetMappingRequestObject) (ConfirmSheetMappingResponseObject, error) {
	mapping := product.Doc{}
	if e := json.Unmarshal(rawBody(ctx)["mapping"], &mapping); e != nil || mapping == nil {
		return nil, platform.Fail(400, "invalid_request", "Укажите сопоставление столбцов")
	}
	out, e := s.Products.SheetPreview(ctx, principal(ctx).User.ID, r.SourceId.String(), mapping, true)
	if e != nil {
		return nil, e
	}
	return reply{status: out.Status, data: out.Body}, nil
}
func (a reply) VisitPreviewSheetSourceResponse(w http.ResponseWriter) error  { return a.write(w) }
func (a reply) VisitConfirmSheetMappingResponse(w http.ResponseWriter) error { return a.write(w) }
