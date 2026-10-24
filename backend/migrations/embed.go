package migrations

import "embed"

// Files contains the goose migrations shipped with each binary.
//
//go:embed *.sql
var Files embed.FS
