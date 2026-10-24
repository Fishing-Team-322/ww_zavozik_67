-- +goose Up
ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL;
ALTER TABLE users ADD COLUMN role text NOT NULL DEFAULT 'owner' CHECK (role IN ('owner', 'admin'));
ALTER TABLE users ADD COLUMN consent_pd_at timestamptz;
CREATE UNIQUE INDEX users_email_normalized ON users (lower(email));

ALTER TABLE companies ADD COLUMN default_horizon integer NOT NULL DEFAULT 30 CHECK (default_horizon IN (30, 60, 90));
ALTER TABLE companies ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE companies ADD CONSTRAINT companies_reserve_valid CHECK (reserve >= 0 AND reserve <> 'NaN'::numeric);
CREATE INDEX memberships_company ON memberships(company_id);

CREATE TABLE auth_sessions (
    id uuid PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    refresh_hash text NOT NULL UNIQUE,
    device text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz
);
CREATE INDEX auth_sessions_user ON auth_sessions(user_id);

CREATE TABLE password_resets (
    token_hash text PRIMARY KEY,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at timestamptz NOT NULL
);
CREATE INDEX password_resets_user ON password_resets(user_id);

CREATE TABLE oauth_identities (
    provider text NOT NULL CHECK (provider IN ('google', 'yandex')),
    subject text NOT NULL,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    PRIMARY KEY(provider, subject),
    UNIQUE(user_id, provider)
);

CREATE TABLE oauth_flows (
    state_hash text PRIMARY KEY,
    provider text NOT NULL,
    verifier text NOT NULL,
    expires_at timestamptz NOT NULL,
    consent_pd_at timestamptz NOT NULL DEFAULT now()
);

-- Shared application state (drafts/UI state); typed financial data stays in its own tables.
CREATE TABLE company_state (
    company_id uuid PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    version bigint NOT NULL DEFAULT 0 CHECK (version >= 0),
    data jsonb NOT NULL DEFAULT '{}' CHECK (jsonb_typeof(data) = 'object'),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE company_state, oauth_flows, oauth_identities, password_resets, auth_sessions;
ALTER TABLE companies DROP CONSTRAINT companies_reserve_valid;
ALTER TABLE companies DROP COLUMN default_horizon, DROP COLUMN updated_at;
DROP INDEX memberships_company;
DROP INDEX users_email_normalized;
ALTER TABLE users DROP COLUMN consent_pd_at, DROP COLUMN role;
-- OAuth-only users cannot be converted to password accounts. Disable password login instead.
UPDATE users SET password_hash = '' WHERE password_hash IS NULL;
ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL;
