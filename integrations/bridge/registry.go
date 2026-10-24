package bridge

import (
	"bytes"
	"context"
	"errors"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/fnsregistry"
)

type RegistryRecord = fnsregistry.Record

// ParseRegistry reuses the Hub parsers; no browser or backend PDF parser is duplicated.
func ParseRegistry(ctx context.Context, data []byte) ([]RegistryRecord, error) {
	if len(data) == 0 || len(data) > 16<<20 {
		return nil, errors.New("registry file exceeds limit")
	}
	out := []RegistryRecord{}
	emit := func(r RegistryRecord) error {
		if len(out) >= 100 {
			return errors.New("at most 100 registry records per upload")
		}
		r.SignatureStatus = "NOT_VERIFIED"
		out = append(out, r)
		return nil
	}
	now := time.Now().UTC()
	var err error
	switch {
	case bytes.HasPrefix(data, []byte("%PDF-")):
		var r RegistryRecord
		r, err = fnsregistry.ParsePDF(bytes.NewReader(data), int64(len(data)), now)
		if err == nil {
			err = emit(r)
		}
	case bytes.HasPrefix(data, []byte("PK")):
		_, err = fnsregistry.ParseZIP(ctx, bytes.NewReader(data), int64(len(data)), now, emit)
	default:
		_, err = fnsregistry.ParseXML(ctx, bytes.NewReader(data), now, emit)
	}
	if err != nil {
		return nil, err
	}
	if len(out) == 0 {
		return nil, errors.New("no registry record found")
	}
	return out, nil
}
