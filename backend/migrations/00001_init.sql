-- +goose Up
-- Начальная схема. Владелец: Бэк 3. Описание таблиц — docs/ARCHITECTURE.md, раздел 5.

CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         text NOT NULL UNIQUE,
    password_hash text NOT NULL,
    telegram_chat_id bigint,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE companies (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text NOT NULL,
    inn         text,
    legal_form  text NOT NULL CHECK (legal_form IN ('ООО', 'ИП')),
    industry    text NOT NULL,
    tax_regime  text NOT NULL DEFAULT 'unknown',
    reserve     numeric(16, 2) NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE memberships (
    user_id    uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    company_id uuid NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    role       text NOT NULL DEFAULT 'owner',
    PRIMARY KEY (user_id, company_id)
);

CREATE TABLE sources (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id     uuid NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    kind           text NOT NULL,
    title          text,
    config         jsonb NOT NULL DEFAULT '{}',  -- без секретов: секреты в config_secret
    config_secret  bytea,                        -- зашифровано ключом приложения
    status         text NOT NULL DEFAULT 'ok',
    error          text,
    last_synced_at timestamptz,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE operations (
    id                text NOT NULL,
    company_id        uuid NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    source_id         uuid REFERENCES sources (id) ON DELETE SET NULL,
    op_date           date NOT NULL,
    amount            numeric(16, 2) NOT NULL CHECK (amount >= 0),
    direction         text NOT NULL CHECK (direction IN ('in', 'out')),
    counterparty_inn  text,
    counterparty_name text,
    purpose           text,
    balance_eod       numeric(16, 2),
    category          text NOT NULL DEFAULT 'other',
    category_method   text NOT NULL DEFAULT 'rule',
    is_internal       boolean NOT NULL DEFAULT false,
    dedup_hash        text NOT NULL,
    is_duplicate      boolean NOT NULL DEFAULT false,
    PRIMARY KEY (company_id, id)
);
CREATE INDEX operations_company_date ON operations (company_id, op_date);
CREATE INDEX operations_dedup ON operations (company_id, dedup_hash);

CREATE TABLE recurring_patterns (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        uuid NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    title             text NOT NULL,
    category          text NOT NULL,
    direction         text NOT NULL,
    counterparty_inn  text,
    counterparty_name text,
    period            text NOT NULL,
    day_of_month      int,
    amount            numeric(16, 2) NOT NULL,
    amount_spread     numeric(16, 2) NOT NULL DEFAULT 0,
    next_date         date NOT NULL,
    confirmed         boolean,  -- null: не проверен пользователем
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE planned_events (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id        uuid NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    source_id         uuid REFERENCES sources (id) ON DELETE SET NULL,
    source_kind       text NOT NULL,
    event_date        date NOT NULL,
    amount            numeric(16, 2) NOT NULL CHECK (amount >= 0),
    direction         text NOT NULL CHECK (direction IN ('in', 'out')),
    title             text NOT NULL,
    category          text,
    counterparty_name text,
    probability       double precision NOT NULL DEFAULT 1,
    status            text NOT NULL DEFAULT 'expected',
    matched_operation_id text,  -- план-факт: какая операция закрыла событие
    created_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX planned_events_company_date ON planned_events (company_id, event_date);

CREATE TABLE forecast_runs (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      uuid NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    scenario_id     uuid,
    as_of           date NOT NULL,
    horizon         int NOT NULL,
    model_used      text NOT NULL,
    low_confidence  boolean NOT NULL DEFAULT false,
    opening_balance numeric(16, 2) NOT NULL,
    safe_to_spend   numeric(16, 2) NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX forecast_runs_company ON forecast_runs (company_id, created_at DESC);

CREATE TABLE forecast_points (
    run_id     uuid NOT NULL REFERENCES forecast_runs (id) ON DELETE CASCADE,
    point_date date NOT NULL,
    p10        numeric(16, 2) NOT NULL,
    p50        numeric(16, 2) NOT NULL,
    p90        numeric(16, 2) NOT NULL,
    components jsonb NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, point_date)
);

CREATE TABLE gaps (
    id            text NOT NULL,
    run_id        uuid NOT NULL REFERENCES forecast_runs (id) ON DELETE CASCADE,
    gap_date      date NOT NULL,
    shortfall     numeric(16, 2) NOT NULL,
    shortfall_p90 numeric(16, 2) NOT NULL,
    probability   double precision NOT NULL,
    causes        jsonb NOT NULL DEFAULT '[]',
    actions       jsonb NOT NULL DEFAULT '[]',
    PRIMARY KEY (run_id, id)
);

CREATE TABLE scenarios (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    title      text NOT NULL,
    preset     boolean NOT NULL DEFAULT false,
    steps      jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE alerts (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id uuid NOT NULL REFERENCES companies (id) ON DELETE CASCADE,
    severity   text NOT NULL,
    title      text NOT NULL,
    body       text,
    gap_id     text,
    read       boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit_log (
    id         bigserial PRIMARY KEY,
    user_id    uuid,
    company_id uuid,
    action     text NOT NULL,  -- view_operations, export, delete_company, ...
    created_at timestamptz NOT NULL DEFAULT now()
);

-- +goose Down
DROP TABLE audit_log, alerts, scenarios, gaps, forecast_points, forecast_runs,
    planned_events, recurring_patterns, operations, sources, memberships, companies, users;
