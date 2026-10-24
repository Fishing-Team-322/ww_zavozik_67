package store

import (
	"context"
	"errors"
	"time"

	"github.com/Fishing-Team-322/ww_zavozik_67/backend/internal/platform"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Postgres struct{ Pool *pgxpool.Pool }

var _ platform.Repository = (*Postgres)(nil)

func Open(ctx context.Context, url string) (*Postgres, error) {
	cfg, err := pgxpool.ParseConfig(url)
	if err != nil {
		return nil, errors.New("invalid DATABASE_URL")
	}
	cfg.MaxConns = 10
	cfg.ConnConfig.ConnectTimeout = 5 * time.Second
	cfg.ConnConfig.RuntimeParams["timezone"] = "UTC"
	pool, err := pgxpool.NewWithConfig(ctx, cfg)
	if err != nil {
		return nil, errors.New("database initialization failed")
	}
	if err = pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, errors.New("database unavailable")
	}
	var ready bool
	if err = pool.QueryRow(ctx, "SELECT to_regclass('company_state') IS NOT NULL AND to_regclass('product_jobs') IS NOT NULL").Scan(&ready); err != nil || !ready {
		pool.Close()
		return nil, errors.New("database migrations missing: run cmd/migrate")
	}
	return &Postgres{pool}, nil
}
func dbError(err error) error {
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.ErrNotFound
	}
	var pg *pgconn.PgError
	if errors.As(err, &pg) && pg.Code == "23505" {
		return platform.ErrConflict
	}
	if err != nil {
		return errors.New("database operation failed")
	}
	return nil
}

type scanner interface{ Scan(...any) error }

func scanUser(row scanner) (u platform.User, err error) {
	err = row.Scan(&u.ID, &u.Email, &u.Role, &u.CreatedAt, &u.PasswordHash)
	return u, dbError(err)
}

const userFields = "id::text,email,role,created_at,password_hash"

func (p *Postgres) CreateUser(ctx context.Context, email string, hash *string) (platform.User, error) {
	return scanUser(p.Pool.QueryRow(ctx, "INSERT INTO users(email,password_hash,consent_pd_at) VALUES($1,$2,now()) RETURNING "+userFields, email, hash))
}
func (p *Postgres) UserByEmail(ctx context.Context, email string) (platform.User, error) {
	return scanUser(p.Pool.QueryRow(ctx, "SELECT "+userFields+" FROM users WHERE lower(email)=$1 AND status='active'", email))
}
func scanSession(row scanner) (s platform.Session, err error) {
	err = row.Scan(&s.ID, &s.UserID, &s.Device, &s.CreatedAt, &s.LastSeenAt, &s.ExpiresAt)
	return s, dbError(err)
}

const sessionFields = "id::text,user_id::text,device,created_at,last_seen_at,expires_at"

func (p *Postgres) NewSession(ctx context.Context, user platform.User, device, hash string, until time.Time) (platform.Session, error) {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return platform.Session{}, dbError(err)
	}
	defer tx.Rollback(ctx)
	// Serialize password changes with session creation, then recheck the authenticated hash.
	var id string
	err = tx.QueryRow(ctx, "SELECT id::text FROM users WHERE id=$1 AND status='active' AND password_hash IS NOT DISTINCT FROM $2 FOR UPDATE", user.ID, user.PasswordHash).Scan(&id)
	if errors.Is(err, pgx.ErrNoRows) {
		return platform.Session{}, platform.ErrCredentials
	}
	if err != nil {
		return platform.Session{}, dbError(err)
	}
	s, err := scanSession(tx.QueryRow(ctx, "INSERT INTO auth_sessions(id,user_id,device,refresh_hash,expires_at) VALUES($1,$2,$3,$4,$5) RETURNING "+sessionFields, uuid.NewString(), id, device, hash, until))
	if err != nil {
		return s, err
	}
	if _, err = tx.Exec(ctx, "UPDATE users SET last_login_at=now() WHERE id=$1", id); err != nil {
		return s, dbError(err)
	}
	return s, dbError(tx.Commit(ctx))
}
func (p *Postgres) Principal(ctx context.Context, sid, uid string) (platform.Principal, error) {
	var out platform.Principal
	err := p.Pool.QueryRow(ctx, `SELECT u.id::text,u.email,u.role,u.created_at,u.password_hash,s.id::text,s.user_id::text,s.device,s.created_at,s.last_seen_at,s.expires_at
 FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.id=$1 AND s.user_id=$2 AND u.status='active' AND s.revoked_at IS NULL AND s.expires_at>now()`, sid, uid).Scan(&out.User.ID, &out.User.Email, &out.User.Role, &out.User.CreatedAt, &out.User.PasswordHash, &out.Session.ID, &out.Session.UserID, &out.Session.Device, &out.Session.CreatedAt, &out.Session.LastSeenAt, &out.Session.ExpiresAt)
	if errors.Is(err, pgx.ErrNoRows) {
		return out, platform.ErrUnauthorized
	}
	if err == nil && out.Session.LastSeenAt.Before(time.Now().Add(-time.Minute)) {
		err = p.Pool.QueryRow(ctx, "UPDATE auth_sessions SET last_seen_at=now() WHERE id=$1 AND revoked_at IS NULL AND expires_at>now() RETURNING last_seen_at", sid).Scan(&out.Session.LastSeenAt)
		if errors.Is(err, pgx.ErrNoRows) {
			return out, platform.ErrUnauthorized
		}
	}
	return out, dbError(err)
}
func (p *Postgres) RotateSession(ctx context.Context, old, next string) (platform.Principal, error) {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return platform.Principal{}, dbError(err)
	}
	defer tx.Rollback(ctx)
	sess, err := scanSession(tx.QueryRow(ctx, `UPDATE auth_sessions SET refresh_hash=$2,last_seen_at=now() WHERE refresh_hash=$1 AND revoked_at IS NULL AND expires_at>now() AND EXISTS(SELECT 1 FROM users WHERE users.id=auth_sessions.user_id AND users.status='active') RETURNING `+sessionFields, old, next))
	if platform.IsStatus(err, 404) {
		return platform.Principal{}, platform.ErrUnauthorized
	}
	if err != nil {
		return platform.Principal{}, err
	}
	user, err := scanUser(tx.QueryRow(ctx, "SELECT "+userFields+" FROM users WHERE id=$1", sess.UserID))
	if err != nil {
		return platform.Principal{}, err
	}
	if err = tx.Commit(ctx); err != nil {
		return platform.Principal{}, dbError(err)
	}
	return platform.Principal{User: user, Session: sess}, nil
}
func (p *Postgres) RevokeSession(ctx context.Context, uid, sid string) error {
	result, err := p.Pool.Exec(ctx, "UPDATE auth_sessions SET revoked_at=now() WHERE user_id=$1 AND id=$2", uid, sid)
	if err != nil {
		return dbError(err)
	}
	if result.RowsAffected() == 0 {
		return platform.ErrNotFound
	}
	return nil
}
func (p *Postgres) ListSessions(ctx context.Context, uid string) ([]platform.Session, error) {
	rows, err := p.Pool.Query(ctx, "SELECT "+sessionFields+" FROM auth_sessions WHERE user_id=$1 AND revoked_at IS NULL AND expires_at>now() ORDER BY created_at DESC", uid)
	if err != nil {
		return nil, dbError(err)
	}
	defer rows.Close()
	out := []platform.Session{}
	for rows.Next() {
		s, err := scanSession(rows)
		if err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, dbError(rows.Err())
}
func (p *Postgres) ChangePassword(ctx context.Context, uid string, old *string, next string) error {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return dbError(err)
	}
	defer tx.Rollback(ctx)
	r, err := tx.Exec(ctx, "UPDATE users SET password_hash=$3 WHERE id=$1 AND password_hash IS NOT DISTINCT FROM $2", uid, old, next)
	if err != nil {
		return dbError(err)
	}
	if r.RowsAffected() == 0 {
		return platform.ErrCredentials
	}
	if _, err = tx.Exec(ctx, "UPDATE auth_sessions SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", uid); err != nil {
		return dbError(err)
	}
	if _, err = tx.Exec(ctx, "DELETE FROM password_resets WHERE user_id=$1", uid); err != nil {
		return dbError(err)
	}
	return dbError(tx.Commit(ctx))
}
func (p *Postgres) SaveReset(ctx context.Context, email, hash string, until time.Time) (platform.User, error) {
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return platform.User{}, dbError(err)
	}
	defer tx.Rollback(ctx)
	u, err := scanUser(tx.QueryRow(ctx, "SELECT "+userFields+" FROM users WHERE lower(email)=$1 FOR UPDATE", email))
	if err != nil {
		return u, err
	}
	if _, err = tx.Exec(ctx, "DELETE FROM password_resets WHERE user_id=$1 OR expires_at<=now()", u.ID); err != nil {
		return u, dbError(err)
	}
	if _, err = tx.Exec(ctx, "INSERT INTO password_resets(token_hash,user_id,expires_at) VALUES($1,$2,$3)", hash, u.ID, until); err != nil {
		return u, dbError(err)
	}
	return u, dbError(tx.Commit(ctx))
}
func (p *Postgres) ResetPassword(ctx context.Context, hash, next string) error {
	invalid := platform.Fail(400, "invalid_reset_token", "Ссылка недействительна или устарела")
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return dbError(err)
	}
	defer tx.Rollback(ctx)
	var uid string
	err = tx.QueryRow(ctx, "SELECT user_id::text FROM password_resets WHERE token_hash=$1 AND expires_at>now()", hash).Scan(&uid)
	if errors.Is(err, pgx.ErrNoRows) {
		return invalid
	}
	if err != nil {
		return dbError(err)
	}
	if _, err = tx.Exec(ctx, "SELECT id FROM users WHERE id=$1 FOR UPDATE", uid); err != nil {
		return dbError(err)
	}
	r, err := tx.Exec(ctx, "DELETE FROM password_resets WHERE token_hash=$1 AND expires_at>now()", hash)
	if err != nil {
		return dbError(err)
	}
	if r.RowsAffected() != 1 {
		return invalid
	}
	if _, err = tx.Exec(ctx, "UPDATE users SET password_hash=$2 WHERE id=$1", uid, next); err != nil {
		return dbError(err)
	}
	if _, err = tx.Exec(ctx, "UPDATE auth_sessions SET revoked_at=now() WHERE user_id=$1 AND revoked_at IS NULL", uid); err != nil {
		return dbError(err)
	}
	if _, err = tx.Exec(ctx, "DELETE FROM password_resets WHERE user_id=$1", uid); err != nil {
		return dbError(err)
	}
	return dbError(tx.Commit(ctx))
}
func (p *Postgres) SaveOAuthFlow(ctx context.Context, hash, provider, verifier string, until time.Time) error {
	if _, err := p.Pool.Exec(ctx, "DELETE FROM oauth_flows WHERE expires_at<=now()"); err != nil {
		return dbError(err)
	}
	_, err := p.Pool.Exec(ctx, "INSERT INTO oauth_flows(state_hash,provider,verifier,expires_at) VALUES($1,$2,$3,$4)", hash, provider, verifier, until)
	return dbError(err)
}
func (p *Postgres) TakeOAuthFlow(ctx context.Context, hash, provider string) (string, error) {
	var verifier string
	err := p.Pool.QueryRow(ctx, "DELETE FROM oauth_flows WHERE state_hash=$1 AND provider=$2 AND expires_at>now() RETURNING verifier", hash, provider).Scan(&verifier)
	if errors.Is(err, pgx.ErrNoRows) {
		return "", platform.Fail(400, "invalid_oauth_state", "Повторите вход через сервис")
	}
	return verifier, dbError(err)
}
func (p *Postgres) OAuthUser(ctx context.Context, provider, subject, email string) (platform.User, error) {
	existing := func() (platform.User, error) {
		return scanUser(p.Pool.QueryRow(ctx, "SELECT u.id::text,u.email,u.role,u.created_at,u.password_hash FROM users u JOIN oauth_identities i ON i.user_id=u.id WHERE i.provider=$1 AND i.subject=$2", provider, subject))
	}
	u, err := existing()
	if err == nil {
		return u, nil
	}
	if !platform.IsStatus(err, 404) {
		return u, err
	}
	tx, err := p.Pool.Begin(ctx)
	if err != nil {
		return u, dbError(err)
	}
	defer tx.Rollback(ctx)
	u, err = scanUser(tx.QueryRow(ctx, "INSERT INTO users(email,consent_pd_at) VALUES($1,now()) RETURNING "+userFields, email))
	if err == nil {
		_, err = tx.Exec(ctx, "INSERT INTO oauth_identities(provider,subject,user_id) VALUES($1,$2,$3)", provider, subject, u.ID)
		err = dbError(err)
	}
	if err != nil {
		_ = tx.Rollback(ctx)
		if platform.IsStatus(err, 409) {
			if prior, e := existing(); e == nil {
				return prior, nil
			}
			return u, platform.Fail(409, "account_exists", "Аккаунт с этой почтой уже существует. Войдите прежним способом")
		}
		return u, err
	}
	return u, dbError(tx.Commit(ctx))
}
