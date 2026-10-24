package service

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"io"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/contracts"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecbank"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/providers/onecodata"
	"github.com/Fishing-Team-322/ww_zavozik_67/integrations/internal/store"
)

type Importer struct{ Store *store.Memory }

func (i Importer) OneCBank(ctx context.Context, r io.Reader, identity contracts.Identity) (contracts.ImportBatch, error) {
	batch, err := (onecbank.Parser{}).Parse(ctx, r, identity)
	if err != nil {
		return batch, err
	}
	return i.finish(batch)
}

func (i Importer) OneCOData(ctx context.Context, client onecodata.Client, cfg onecodata.Config) (contracts.ImportBatch, error) {
	batch, err := client.Fetch(ctx, cfg)
	if err != nil {
		return batch, err
	}
	return i.finish(batch)
}

func (i Importer) finish(batch contracts.ImportBatch) (contracts.ImportBatch, error) {
	var random [16]byte
	if _, err := rand.Read(random[:]); err != nil {
		return batch, err
	}
	batch.ImportID = hex.EncodeToString(random[:])
	batch.ImportedAt = time.Now().UTC().Format(time.RFC3339Nano)
	if i.Store != nil {
		batch = i.Store.Add(batch)
	}
	return batch, nil
}
