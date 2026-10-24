package httpapi

import (
	"context"
	"mime/multipart"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/product"
	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/store"
)

func (s *Server) initProduct() {
	if s.Products != nil {
		return
	}
	s.Products = &product.Service{ML: s.ML, Fallback: s.Fallback}
	if s.Accounts != nil {
		if db, yes := s.Accounts.Repo.(*store.Postgres); yes {
			s.Products.DB = db
		}
	}
}
func (s *Server) productReply(ctx context.Context, op string, upload *multipart.Reader) (reply, error) {
	p, _ := ctx.Value(principalKey).(platform.Principal)
	result, err := s.Products.Execute(ctx, op, p, request(ctx), rawBody(ctx), upload)
	if err != nil {
		return reply{}, err
	}
	return reply{status: result.Status, data: result.Body, dataBytes: result.Data, filename: result.Filename, mime: result.MIME}, nil
}
