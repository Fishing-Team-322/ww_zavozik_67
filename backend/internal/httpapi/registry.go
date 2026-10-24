package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"io"
	"net/http"
)

func (s *Server) registryReply(ctx context.Context, cid, action string) (reply, error) {
	out, err := s.Products.Registry(ctx, principal(ctx).User.ID, cid, action, request(ctx))
	if err != nil {
		return reply{}, err
	}
	return reply{status: out.Status, data: out.Body}, nil
}
func (s *Server) ListRegistryDocuments(ctx context.Context, r ListRegistryDocumentsRequestObject) (ListRegistryDocumentsResponseObject, error) {
	return s.registryReply(ctx, r.CompanyId.String(), "list")
}
func (s *Server) PreviewRegistryDocument(ctx context.Context, r PreviewRegistryDocumentRequestObject) (PreviewRegistryDocumentResponseObject, error) {
	return s.registryReply(ctx, r.CompanyId.String(), "preview")
}
func (s *Server) ConfirmRegistryDocument(ctx context.Context, r ConfirmRegistryDocumentRequestObject) (ConfirmRegistryDocumentResponseObject, error) {
	for _, key := range []string{"preview_id", "record_index", "target"} {
		if _, ok := rawBody(ctx)[key]; !ok {
			return nil, platform.Fail(400, "invalid_request", "Не заполнено поле: "+key)
		}
	}
	data, _ := json.Marshal(rawBody(ctx))
	request(ctx).Body = io.NopCloser(bytes.NewReader(data))
	return s.registryReply(ctx, r.CompanyId.String(), "confirm")
}
func (a reply) VisitListRegistryDocumentsResponse(w http.ResponseWriter) error   { return a.write(w) }
func (a reply) VisitPreviewRegistryDocumentResponse(w http.ResponseWriter) error { return a.write(w) }
func (a reply) VisitConfirmRegistryDocumentResponse(w http.ResponseWriter) error { return a.write(w) }
