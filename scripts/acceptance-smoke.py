"""Repeatable acceptance against an isolated loopback stack; standard library only.

Creates synthetic test data. Report contains no credentials. Optional private state
is used only to verify persistence after a stack restart and must not be published.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import math
import time
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--api-url', default='http://localhost:8080')
    p.add_argument('--output', required=True)
    p.add_argument('--state')
    p.add_argument('--verify-restart', action='store_true')
    p.add_argument('--require-ml', action='store_true')
    args = p.parse_args()
    origin = args.api_url.rstrip('/')
    parsed = urlparse(origin)
    if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username or parsed.password or parsed.path:
        raise ValueError('Acceptance is restricted to an isolated loopback API origin')
    checks = []
    token = None

    def call(method, path, body=None, *, raw=None, content_type='application/json', want=200):
        data = raw if raw is not None else json.dumps(body, ensure_ascii=False).encode() if body is not None else b'' if method == 'POST' else None
        headers = {'Content-Type': content_type}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        for attempt in range(5):
            try:
                with urlopen(Request(origin + path, data=data, headers=headers, method=method), timeout=40) as r:
                    code, payload = r.status, r.read()
            except HTTPError as e:
                code, payload = e.code, e.read()
            obj = json.loads(payload) if payload else None
            if code == 409 and method == 'GET' and obj and obj.get('code') == 'version_conflict' and attempt < 4:
                time.sleep(.5)
                continue
            if code != want:
                raise AssertionError(f'{method} {path}: HTTP {code}, expected {want}; code={obj.get("code") if isinstance(obj, dict) else "unknown"}')
            return obj
        raise AssertionError('retry exhausted')

    def idle(base):
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            state = call('GET', base + '/updates')
            if not state['pending_jobs']:
                if state['last_job_error']:
                    raise AssertionError('Worker reported a failed operation')
                return state
            time.sleep(.5)
        raise AssertionError('Worker did not settle within 150 seconds')

    def upload(base, content):
        boundary = 'case-' + uuid.uuid4().hex
        raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="acceptance.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode() + content + f'\r\n--{boundary}--\r\n'.encode())
        job = call('POST', base + '/uploads', raw=raw, content_type='multipart/form-data; boundary=' + boundary, want=202)
        deadline = time.monotonic() + 150
        while job['status'] not in ('done', 'failed') and time.monotonic() < deadline:
            time.sleep(.5)
            job = call('GET', '/v1/jobs/' + job['id'])
        if job['status'] != 'done':
            raise AssertionError('Import did not complete')
        return call('GET', job['result_ref'])

    def checked(name, evidence):
        checks.append({'check': name, 'status': 'passed', 'evidence': evidence})
        print(name + ': passed', flush=True)

    call('GET', '/healthz')
    call('GET', '/readyz')
    if args.require_ml:
        # API readiness covers PostgreSQL. After a stack restart, the Python
        # process can still be loading its trained artifacts while API requests
        # correctly use the fallback. Wait for model readiness, not just a port.
        deadline = time.monotonic() + 60
        while call('GET', '/healthz').get('ml') != 'ok':
            if time.monotonic() >= deadline:
                raise AssertionError('Trained ML did not become ready within 60 seconds')
            time.sleep(.5)
        checked('trained_ml_readiness', 'Trained model service is ready before financial acceptance')
    if args.verify_restart:
        if not args.state:
            raise ValueError('--state is required for restart verification')
        state = json.loads(Path(args.state).read_text())
        login = call('POST', '/v1/auth/login', {'email': state['email'], 'password': state['password']})
        token = login['access_token']
        base = '/v1/companies/' + state['company_id']
        summary = call('GET', base + '/operations/summary')
        if summary['total_in'] != state['total_in'] or summary['total_out'] != state['total_out']:
            raise AssertionError('Financial facts changed across restart')
        events = call('GET', base + '/events')
        if not any(e['id'] == state['event_id'] for e in events):
            raise AssertionError('Plan disappeared after restart')
        taxes = call('GET', base + '/taxes')
        if not any(o['id'] == state['tax_id'] and o['status'] == 'cancelled' for o in taxes['obligations']):
            raise AssertionError('Tax history disappeared after restart')
        idle(base)
        fresh = call('GET', base + '/forecast')
        if args.require_ml:
            assert fresh['fallback_used'] is False, 'Trained ML unavailable after restart'
        checked('persistence_after_restart', 'Authenticated account, operations, planned event and cancelled tax history remain available')
    else:
        email = 'case-' + uuid.uuid4().hex + '@example.invalid'
        password = 'Synthetic-Acceptance-' + uuid.uuid4().hex
        user = call('POST', '/v1/auth/register', {'email': email, 'password': password, 'consent_pd': True}, want=201)
        token = user['access_token']
        company = call('POST', '/v1/companies', {'name': 'Синтетическая приёмка ПУЛЬС', 'legal_form': 'ООО', 'industry': 'services'}, want=201)
        base = '/v1/companies/' + company['id']
        # Reserve three observed days for the next statement; future bank facts are rejected.
        now = date.today()
        as_of = now - timedelta(days=3)
        balance = 250000
        table = [['date', 'amount', 'direction', 'counterparty', 'purpose', 'balance', 'id']]
        for i in range(119, -1, -1):
            day = as_of - timedelta(days=i)
            incoming, outgoing = (11000 + i % 7 * 100, 8000 + i % 5 * 50) if day.weekday() < 5 else (0, 0)
            balance += incoming - outgoing
            table += [[day.isoformat(), incoming, 'in', 'Тестовый клиент', 'Оплата услуг по договору', balance, f'in-{i}'], [day.isoformat(), outgoing, 'out', 'Тестовый поставщик', 'Оплата материалов', balance, f'out-{i}']]

        def csv_bytes(rows):
            s = io.StringIO(); csv.writer(s, delimiter=';', lineterminator='\n').writerows(rows); return s.getvalue().encode()

        content = csv_bytes(table)
        report = upload(base, content)
        assert report['added'] == 240 and not report['errors'], 'Unexpected first import result'
        idle(base)
        checked('csv_import', '240 synthetic operations, no row errors')
        duplicate = upload(base, content)
        assert duplicate['added'] == 0 and duplicate['duplicates'] == 240, 'Duplicate import changed facts'
        idle(base)
        checked('duplicate_import', '0 new operations; 240 duplicates identified')
        before = call('GET', base + '/forecast')
        assert len(before['points']) == 30 and before['model_version'], 'Forecast is incomplete'
        if args.require_ml:
            assert before['fallback_used'] is False, 'Real trained model required, but fallback was used'
            assert before['model_used'] in ('ensemble', 'gbm_global'), 'Unexpected forecasting model'
        checked('forecast', {'model': before['model_used'], 'fallback_used': before['fallback_used'], 'horizon': len(before['points']), 'warnings': before['warnings']})
        due = (as_of + timedelta(days=5)).isoformat()
        amount = round(before['opening_balance'] + 100000, 2)
        tax = {'request_id': str(uuid.uuid4()), 'kind': 'other', 'period': 'acceptance', 'year': int(due[:4]), 'due_date': due, 'amount': amount, 'title': 'Дополнительный подтверждённый налог', 'source_ref': 'Синтетический расчёт приёмки', 'confirmed': True, 'additional': True}
        call('POST', base + '/taxes/preview', tax)
        saved = call('POST', base + '/taxes', tax, want=201)
        repeated = call('POST', base + '/taxes', tax, want=201)
        assert saved['id'] == repeated['id'], 'Repeated submission created a second obligation'
        idle(base)
        after = call('GET', base + '/forecast')
        for a, b in zip(before['points'], after['points']):
            shift = amount if a['date'] >= due else 0
            assert math.isclose(a['p50'] - b['p50'], shift, abs_tol=.05), 'Tax missing or counted twice'
        assert after['gaps'], 'Expected cash-gap warning is absent'
        checked('tax_and_gap', 'Confirmed tax is applied once on its due date; gap date, shortfall and probability returned')
        scenario = call('POST', base + '/scenarios/preview', {'steps': [{'kind': 'scale_revenue', 'factor': .8}]})
        assert len(scenario['scenario']['points']) == 30, 'Scenario forecast is incomplete'
        checked('scenario', 'Server returned baseline and revenue -20% scenario')
        call('POST', '/v1/taxes/' + saved['id'] + '/cancel', want=204)
        idle(base)
        restored = call('GET', base + '/forecast')
        for a, b in zip(before['points'], restored['points']):
            assert math.isclose(a['p50'], b['p50'], abs_tol=.05), 'Cancelled tax still affects forecast'
        event = call('POST', base + '/events', {'date': as_of.isoformat(), 'amount': 777777.77, 'direction': 'in', 'title': 'Платёж, который задерживается', 'counterparty_name': 'Отдельный клиент'}, want=201)
        idle(base)
        more = [table[0]]
        for i in range(1, 4):
            day = as_of + timedelta(days=i)
            incoming, outgoing = (11000, 8000) if day.weekday() < 5 else (0, 0)
            balance += incoming - outgoing
            more += [[day.isoformat(), incoming, 'in', 'Тестовый клиент', 'Оплата услуг по договору', balance, f'new-in-{i}'], [day.isoformat(), outgoing, 'out', 'Тестовый поставщик', 'Оплата материалов', balance, f'new-out-{i}']]
        report = upload(base, csv_bytes(more)); assert report['added'] == 6, f'Expected 6 new synthetic rows: {report}'
        state = idle(base)
        assert state['forecast_revision'] == state['data_revision'], 'Forecast not refreshed by worker'
        missed = call('GET', base + '/plan-fact/missed')
        assert any(e['id'] == event['id'] for e in missed['missed']), 'Missed planned receipt not identified'
        alerts = call('GET', base + '/alerts?kind=missed_payment')
        assert alerts['items'], 'Missed-payment alert not created'
        rows = call('GET', base + '/plan-fact')
        assert any(r['observed'] and r['deviation'] is not None for r in rows), 'Observed plan/fact missing'
        checked('automatic_plan_fact_update', 'New statement triggered reconciliation, missed-payment alert and saved current forecast revision')
        checks.append({'check': 'live_external_integrations', 'status': 'skipped', 'evidence': 'No external credentials; isolated adapter tests are separate'})
        print('live_external_integrations: skipped (no credentials)', flush=True)
        if args.state:
            summary = call('GET', base + '/operations/summary')
            state = {'email': email, 'password': password, 'company_id': company['id'], 'tax_id': saved['id'], 'event_id': event['id'], 'total_in': summary['total_in'], 'total_out': summary['total_out']}
            state_file = Path(args.state); state_file.write_text(json.dumps(state), encoding='utf8'); state_file.chmod(0o600)
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'synthetic': True, 'api_origin': origin, 'checks': checks}, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
