-- Run with: docker compose exec -T postgres psql -U zavozik -d zavozik -v company_id=<uuid> -f /dev/stdin < scripts/seed-demo.sql
-- Idempotent demo data for one existing company. Never run against production data.
\set ON_ERROR_STOP on
BEGIN;

CREATE TEMP TABLE demo_target AS SELECT id FROM companies WHERE id = :'company_id'::uuid;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM demo_target) THEN
    RAISE EXCEPTION 'Company not found';
  END IF;
END $$;

UPDATE companies SET tax_regime = 'usn6', reserve = 120000, industry = 'Оптовая торговля', updated_at = now()
WHERE id IN (SELECT id FROM demo_target) AND name = 'Компания';

INSERT INTO sources (id, company_id, kind, title, status, enabled, last_synced_at, extra)
SELECT md5(id::text || ':demo:source')::uuid, id, 'upload', 'Демо-выписка · расчётный счёт', 'ok', true, now() - interval '1 day',
       '{"records": 0, "source": "upload"}'::jsonb
FROM demo_target ON CONFLICT (id) DO NOTHING;

WITH entries AS (
  SELECT target.id AS company_id, day::date AS op_date, kind,
         CASE kind WHEN 1 THEN 52000 + (extract(day from day)::int % 5) * 4000
                   WHEN 2 THEN 24000 + (extract(day from day)::int % 4) * 2400
                   WHEN 3 THEN 62000 + (extract(day from day)::int % 3) * 3100
                   ELSE 18500 + (extract(day from day)::int % 4) * 1200 END::numeric(16,2) AS amount,
         CASE WHEN kind IN (1,2) THEN 'in' ELSE 'out' END AS direction,
         CASE kind WHEN 1 THEN 'ООО Северный торговый дом' WHEN 2 THEN 'ООО Альфа Ритейл'
                   WHEN 3 THEN 'ООО Поставки Плюс' ELSE 'ООО Склад-Сервис' END AS counterparty_name,
         CASE kind WHEN 1 THEN '7701234567' WHEN 2 THEN '7712345678'
                   WHEN 3 THEN '7723456789' ELSE '7734567890' END AS counterparty_inn,
         CASE kind WHEN 1 THEN 'Оплата товара по договору поставки' WHEN 2 THEN 'Оплата счёта за продукцию'
                   WHEN 3 THEN 'Закупка товара' ELSE 'Аренда склада и услуги хранения' END AS purpose,
         CASE kind WHEN 1 THEN 'revenue_b2b' WHEN 2 THEN 'revenue_b2b'
                   WHEN 3 THEN 'supplier' ELSE 'rent' END AS category
  FROM demo_target target
  CROSS JOIN generate_series(current_date - 119, current_date - 1, interval '1 day') day
  CROSS JOIN generate_series(1, 4) kind
), numbered AS (
  SELECT *, md5(company_id::text || ':demo:operation:' || op_date::text || ':' || kind) AS demo_id,
         480000 + sum(CASE WHEN direction = 'in' THEN amount ELSE -amount END)
           OVER (PARTITION BY company_id ORDER BY op_date RANGE BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_balance
  FROM entries
)
INSERT INTO operations (id, company_id, source_id, op_date, amount, direction, counterparty_inn,
                        counterparty_name, purpose, balance_eod, category, category_method, dedup_hash, extra)
SELECT demo_id, company_id, md5(company_id::text || ':demo:source')::uuid, op_date, amount, direction,
       counterparty_inn, counterparty_name, purpose, running_balance, category, 'rule', demo_id,
       jsonb_build_object('source', 'upload')
FROM numbered ON CONFLICT (company_id, id) DO NOTHING;

UPDATE sources SET extra = jsonb_set(extra, '{records}',
  to_jsonb((SELECT count(*) FROM operations o WHERE o.source_id = sources.id)))
WHERE id IN (SELECT md5(id::text || ':demo:source')::uuid FROM demo_target);

WITH plans (key, offset_days, amount, direction, title, category, counterparty_name, counterparty_inn, status, additional) AS (
  VALUES
    ('customer-1', 4, 310000::numeric, 'in', 'Оплата партии товара · Северный торговый дом', 'revenue_b2b', 'ООО Северный торговый дом', '7701234567', 'expected', true),
    ('supplier-1', 6, 240000::numeric, 'out', 'Оплата поставщику · Поставки Плюс', 'supplier', 'ООО Поставки Плюс', '7723456789', 'expected', true),
    ('rent', 9, 86000::numeric, 'out', 'Аренда склада', 'rent', 'ООО Склад-Сервис', '7734567890', 'expected', false),
    ('customer-2', 13, 185000::numeric, 'in', 'Оплата счёта · Альфа Ритейл', 'revenue_b2b', 'ООО Альфа Ритейл', '7712345678', 'expected', true),
    ('salary', 16, 140000::numeric, 'out', 'Заработная плата', 'salary', 'Сотрудники', NULL, 'expected', false),
    ('tax', 22, 48000::numeric, 'out', 'Аванс УСН', 'tax', 'ФНС России', NULL, 'expected', false),
    ('equipment', 8, 1100000::numeric, 'out', 'Покупка складского оборудования', 'supplier', 'ООО Поставки Плюс', '7723456789', 'expected', true),
    ('past-plan', -8, 175000::numeric, 'in', 'Плановая оплата · Альфа Ритейл', 'revenue_b2b', 'ООО Альфа Ритейл', '7712345678', 'received', false),
    ('past-missed', -3, 95000::numeric, 'in', 'Просроченная оплата клиента', 'revenue_b2b', 'ООО Альфа Ритейл', '7712345678', 'missed', false)
)
INSERT INTO planned_events (id, company_id, source_kind, event_date, amount, direction, title, category,
                            counterparty_name, probability, status, extra)
SELECT md5(target.id::text || ':demo:event:' || plans.key)::uuid, target.id, 'manual', current_date + offset_days,
       amount, direction, title, category, counterparty_name, 1, status,
       jsonb_build_object('source', 'manual', 'additional', additional, 'counterparty_inn', counterparty_inn)
FROM demo_target target CROSS JOIN plans ON CONFLICT (id) DO NOTHING;

WITH patterns (key, title, category, direction, counterparty_name, amount, next_days) AS (
  VALUES ('rent', 'Аренда склада', 'rent', 'out', 'ООО Склад-Сервис', 86000::numeric, 9),
         ('salary', 'Заработная плата', 'salary', 'out', 'Сотрудники', 140000::numeric, 16),
         ('tax', 'Аванс УСН', 'tax', 'out', 'ФНС России', 48000::numeric, 22),
         ('sales', 'Поступления от Северного торгового дома', 'revenue_b2b', 'in', 'ООО Северный торговый дом', 310000::numeric, 4)
)
INSERT INTO recurring_patterns (id, company_id, title, category, direction, counterparty_name,
                                period, day_of_month, amount, next_date, confirmed, active, extra)
SELECT md5(target.id::text || ':demo:recurring:' || patterns.key)::uuid, target.id, title, category, direction,
       counterparty_name, 'monthly', extract(day from current_date + next_days)::int, amount,
       current_date + next_days, true, true, '{"origin":"manual"}'::jsonb
FROM demo_target target CROSS JOIN patterns ON CONFLICT (id) DO NOTHING;

WITH demo_scenarios (key, title, steps) AS (
  VALUES ('delay', 'Клиент задержит оплату на неделю', '[{"kind":"delay_counterparty","counterparty_name":"ООО Северный торговый дом","delay_days":7}]'::jsonb),
         ('expense', 'Непредвиденная закупка', jsonb_build_array(jsonb_build_object('kind','add_expense','amount',180000,'date',current_date + 12))),
         ('growth', 'Рост выручки на 15%', '[{"kind":"scale_revenue","factor":1.15}]'::jsonb)
)
INSERT INTO scenarios (id, company_id, title, preset, steps, extra)
SELECT md5(target.id::text || ':demo:scenario:' || key)::uuid, target.id, title, false, steps, '{}'::jsonb
FROM demo_target target CROSS JOIN demo_scenarios ON CONFLICT (id) DO NOTHING;

WITH documents (key, kind, data) AS (
  VALUES
    ('invoice-sale', 'invoice', jsonb_build_object('number','Д-104','direction','issued','amount',310000,'paid_amount',0,'issued_at',current_date-3,'due_at',current_date+4,'expected_pay_at',current_date+4,'status','open','source','manual','counterparty_name','ООО Северный торговый дом','counterparty_inn','7701234567')),
    ('invoice-buy', 'invoice', jsonb_build_object('number','П-208','direction','received','amount',240000,'paid_amount',40000,'issued_at',current_date-5,'due_at',current_date+6,'expected_pay_at',current_date+6,'status','partial','source','manual','counterparty_name','ООО Поставки Плюс','counterparty_inn','7723456789')),
    ('invoice-overdue', 'invoice', jsonb_build_object('number','Д-099','direction','issued','amount',95000,'paid_amount',0,'issued_at',current_date-14,'due_at',current_date-3,'expected_pay_at',current_date-3,'status','overdue','source','manual','counterparty_name','ООО Альфа Ритейл','counterparty_inn','7712345678')),
    ('contract-sale', 'contract', jsonb_build_object('number','КП-2026/14','direction','in','total',620000,'prepayment',0,'deferral_days',14,'schedule',jsonb_build_array(jsonb_build_object('date',current_date+4,'amount',310000,'status','expected'),jsonb_build_object('date',current_date+34,'amount',310000,'status','expected')),'source','manual','counterparty_name','ООО Северный торговый дом','counterparty_inn','7701234567')),
    ('contract-rent', 'contract', jsonb_build_object('number','А-18','direction','out','total',1032000,'prepayment',0,'deferral_days',0,'schedule',jsonb_build_array(jsonb_build_object('date',current_date+9,'amount',86000,'status','expected')),'source','manual','counterparty_name','ООО Склад-Сервис','counterparty_inn','7734567890'))
)
INSERT INTO product_documents (id, company_id, kind, data)
SELECT md5(target.id::text || ':demo:document:' || key)::uuid, target.id, kind, data
FROM demo_target target CROSS JOIN documents ON CONFLICT (id) DO NOTHING;

INSERT INTO alerts (id, company_id, severity, title, body, kind, read, extra)
SELECT md5(id::text || ':demo:alert:overdue')::uuid, id, 'warning', 'Клиент задержал оплату',
       'Счёт Д-099 просрочен. Проверьте план поступлений и свяжитесь с контрагентом.',
       'payment_delay', false, '{"ref":{"screen":"documents"}}'::jsonb
FROM demo_target ON CONFLICT (id) DO NOTHING;

UPDATE companies SET data_revision = data_revision + 1 WHERE id IN (SELECT id FROM demo_target);
COMMIT;
