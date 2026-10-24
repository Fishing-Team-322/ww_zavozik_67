// Package store implements account and company persistence using pgx/Postgres.
//
// Schema: backend/migrations (goose). All values in queries are bound parameters.
// Financial imports, forecast persistence and River jobs remain separate work.
package store
