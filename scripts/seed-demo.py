"""Populate an isolated local stack through its real API using the case dataset.

Standard library only. Read a ZIP or extracted dataset, preserve integer kopecks,
and checkpoint the date shift so repeat runs never move already imported facts.
Credentials are read from PULS_DEMO_PASSWORD, never written to the checkpoint.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sys
import time
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class SeedError(RuntimeError):
    pass


class Dataset:
    def __init__(self, path: Path):
        self.path = path
        self.archive = zipfile.ZipFile(path) if path.is_file() else None
        if self.archive:
            metadata = [n for n in self.archive.namelist() if PurePosixPath(n).name == 'companies.csv']
            if len(metadata) != 1:
                raise SeedError('Dataset ZIP must contain one companies.csv')
            self.prefix = str(PurePosixPath(metadata[0]).parent)
            self.prefix = '' if self.prefix == '.' else self.prefix + '/'
        else:
            if not (path / 'companies.csv').is_file():
                raise SeedError('Pass the dataset ZIP or directory containing companies.csv and statements/')
            self.prefix = ''
        self.companies = {row['company_id']: row for row in self.rows(self.read('companies.csv'))}

    @staticmethod
    def rows(raw: bytes):
        return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')), delimiter=';'))

    def read(self, member: str) -> bytes:
        if self.archive:
            name = self.prefix + member
            if self.archive.getinfo(name).file_size > 32 * 1024 * 1024:
                raise SeedError('A dataset file exceeds 32 MiB')
            return self.archive.read(name)
        return (self.path / member).read_bytes()

    def statement(self, company_id: str):
        if company_id not in self.companies or not company_id.isalnum():
            raise SeedError(f'Unknown dataset company: {company_id}')
        raw = self.read(f'statements/{company_id}.csv')
        rows = self.rows(raw)
        if not rows or any(r.get('company_id') != company_id for r in rows):
            raise SeedError(f'Empty or foreign statement: {company_id}')
        return raw, rows


def money(cell: str, *, signed=False) -> str:
    try:
        value = Decimal(cell)
    except InvalidOperation as exc:
        raise SeedError('Invalid dataset amount') from exc
    if not value.is_finite() or abs(value) > Decimal('10000000000000') or (not signed and value < 0) or value != value.quantize(Decimal('.01')):
        raise SeedError('Amount must be finite with kopeck precision')
    return format(value, '.2f')


def statement_chunks(company_id: str, rows: list[dict], anchor: date | None, fingerprint: str, limit=3 * 1024 * 1024):
    original_last = max(date.fromisoformat(r['operation_date']) for r in rows)
    shift = (anchor - original_last).days if anchor else 0
    header = ['date', 'amount', 'direction', 'counterparty_inn', 'counterparty_name', 'purpose', 'balance', 'id']
    direction = {'Поступление': 'in', 'Списание': 'out'}
    chunks, current = [], []
    size = len((';'.join(header) + '\n').encode())
    last_balance = None
    for row in sorted(rows, key=lambda r: (r['operation_date'], r['operation_id'])):
        if row['direction'] not in direction:
            raise SeedError('Unknown dataset operation direction')
        dt = date.fromisoformat(row['operation_date']) + timedelta(days=shift)
        if dt > datetime.now(timezone.utc).date():
            raise SeedError('The selected date shift creates future bank facts')
        balance = money(row['balance_eod'], signed=True) if row['balance_eod'].strip() else ''
        if dt == original_last + timedelta(days=shift) and balance:
            last_balance = balance
        entry = [dt.isoformat(), money(row['amount']), direction[row['direction']], row['counterparty_inn'], row['counterparty_name'], row['payment_purpose'], balance, f'demo:{fingerprint[:12]}:{company_id}:{row["operation_id"]}']
        output = io.StringIO(newline='')
        csv.writer(output, delimiter=';', lineterminator='\n').writerow(entry)
        encoded = output.getvalue().encode('utf-8')
        if len(encoded) > limit:
            raise SeedError('One dataset row exceeds the import limit')
        if current and size + len(encoded) > limit:
            chunks.append((';'.join(header) + '\n').encode() + b''.join(current))
            current, size = [], len((';'.join(header) + '\n').encode())
        current.append(encoded)
        size += len(encoded)
    if last_balance is None:
        raise SeedError('The last statement date needs a known closing balance')
    if current:
        chunks.append((';'.join(header) + '\n').encode() + b''.join(current))
    return chunks, original_last + timedelta(days=shift), Decimal(last_balance), shift


class API:
    def __init__(self, origin: str):
        parsed = urlparse(origin)
        if parsed.scheme not in ('http', 'https') or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment:
            raise SeedError('Demo seeding requires a loopback API origin')
        self.origin, self.token = origin.rstrip('/'), None

    def call(self, method, path, body=None, *, raw=None, content_type='application/json', expected=(200,)):
        data = raw if raw is not None else json.dumps(body, ensure_ascii=False).encode() if body is not None else b'' if method == 'POST' else None
        headers = {'Content-Type': content_type}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        for attempt in range(6):
            try:
                with urlopen(Request(self.origin + path, data=data, headers=headers, method=method), timeout=60) as response:
                    status, payload = response.status, response.read()
            except HTTPError as exc:
                status, payload = exc.code, exc.read()
            obj = json.loads(payload) if payload else None
            if status == 409 and method == 'GET' and isinstance(obj, dict) and obj.get('code') == 'version_conflict' and attempt < 5:
                time.sleep(.5)
                continue
            if status not in expected:
                code = obj.get('code', 'unknown') if isinstance(obj, dict) else 'unknown'
                raise SeedError(f'{method} {path}: HTTP {status}, code={code}')
            return obj
        raise SeedError('Concurrent data changes did not settle')

    def authenticate(self, email, password):
        try:
            result = self.call('POST', '/v1/auth/login', {'email': email, 'password': password})
        except SeedError as exc:
            if 'HTTP 401' not in str(exc):
                raise
            result = self.call('POST', '/v1/auth/register', {'email': email, 'password': password, 'consent_pd': True}, expected=(201,))
        self.token = result['access_token']

    def wait_job(self, job):
        stop = time.monotonic() + 240
        while job['status'] in ('queued', 'running') and time.monotonic() < stop:
            time.sleep(.5)
            job = self.call('GET', '/v1/jobs/' + job['id'])
        if job['status'] != 'done':
            raise SeedError('Import did not finish successfully; check the worker and job status')
        return job

    def idle(self, base):
        stop = time.monotonic() + 240
        while time.monotonic() < stop:
            status = self.call('GET', base + '/updates')
            if not status['pending_jobs']:
                if status['last_job_error']:
                    raise SeedError('Background recompute failed; inspect the local worker')
                return
            time.sleep(.5)
        raise SeedError('Worker did not settle within 240 seconds')

    def upload(self, base, content):
        boundary = 'demo-' + uuid.uuid4().hex
        raw = f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="demo-case.csv"\r\nContent-Type: text/csv\r\n\r\n'.encode() + content + f'\r\n--{boundary}--\r\n'.encode()
        job = self.call('POST', base + '/uploads', raw=raw, content_type='multipart/form-data; boundary=' + boundary, expected=(202,))
        if job.get('needs_mapping'):
            raise SeedError('Canonical seed CSV unexpectedly requires column mapping')
        done = self.wait_job(job)
        report = self.call('GET', done['result_ref'])
        if report['errors']:
            raise SeedError('Import rejected rows; existing data was preserved')
        return report


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def demo_plans(api, base, dataset_id, as_of, balance, monthly_out):
    """Clearly synthetic future obligations; no duplicate SQL event projections."""
    def dt(days):
        return (as_of + timedelta(days=days)).isoformat()

    def amount(factor):
        return float(max(Decimal('1000'), monthly_out * Decimal(str(factor))).quantize(Decimal('.01')))

    def ensure(kind, key, body):
        number = f'DEMO-{dataset_id}-{key}'
        rows = api.call('GET', base + '/' + kind)
        if not any(row.get('number') == number for row in rows):
            api.call('POST', base + '/' + kind, {'number': number, **body}, expected=(201,))

    party = 'Демо · новый клиент'
    ensure('invoices', 'CLIENT', {'direction': 'issued', 'counterparty_name': party, 'amount': amount(.6), 'issued_at': dt(-3), 'due_at': dt(5), 'additional': True})
    ensure('invoices', 'SUPPLIER', {'direction': 'received', 'counterparty_name': 'Демо · поставщик', 'amount': amount(.35), 'paid_amount': amount(.1), 'issued_at': dt(-5), 'due_at': dt(9), 'additional': True})
    ensure('invoices', 'LATE', {'direction': 'issued', 'counterparty_name': 'Демо · клиент с задержкой', 'amount': amount(.17), 'issued_at': dt(-20), 'due_at': dt(-3), 'additional': True})
    ensure('contracts', 'CONTRACT', {'direction': 'in', 'counterparty_name': 'Демо · заказчик проекта', 'total': amount(.8), 'prepayment': amount(.2), 'start_date': dt(7), 'deferral_days': 14, 'additional': True})
    title = f'Демо · новое оборудование · {dataset_id}'
    if not any(row['title'] == title for row in api.call('GET', base + '/events')):
        expense = float((max(Decimal(0), balance) + monthly_out * 2).quantize(Decimal('.01'))) if dataset_id == 'C008' else amount(.15)
        api.call('POST', base + '/events', {'title': title, 'date': dt(8), 'amount': expense, 'direction': 'out', 'category': 'other', 'additional': True}, expected=(201,))
    api.call('POST', base + '/taxes', {'request_id': str(uuid.uuid5(uuid.NAMESPACE_URL, base + ':demo-tax')), 'kind': 'other', 'period': 'Демонстрационное обязательство', 'year': as_of.year, 'due_date': dt(14), 'amount': amount(.05), 'title': 'Демо · налоговый платёж', 'source_ref': 'Синтетическая сумма для демонстрации; не расчёт налога из банковских поступлений', 'confirmed': True, 'additional': True}, expected=(201,))
    scenarios = api.call('GET', base + '/scenarios')
    for title, step in [('Демо · клиент задержит оплату', {'kind': 'delay_counterparty', 'counterparty_name': party, 'delay_days': 21}), ('Демо · снижение выручки', {'kind': 'scale_revenue', 'factor': .8}), ('Демо · внеплановый расход', {'kind': 'add_expense', 'amount': amount(.5), 'date': dt(12)})]:
        if not any(row['title'] == title for row in scenarios):
            api.call('POST', base + '/scenarios', {'title': title, 'steps': [step]}, expected=(201,))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True, type=Path)
    parser.add_argument('--api-url', default='http://localhost:8080')
    parser.add_argument('--email', default='demo@puls.local')
    parser.add_argument('--companies', nargs='+', default=['C001', 'C008', 'C016'])
    parser.add_argument('--all', action='store_true', help='Import all dataset companies instead of the three examples')
    parser.add_argument('--as-of', help='YYYY-MM-DD or original; default yesterday UTC, pinned in state')
    parser.add_argument('--state', type=Path, default=Path('.local/demo-seed.json'))
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--history-only', action='store_true')
    args = parser.parse_args(argv)
    dataset = Dataset(args.dataset)
    selected = sorted(dataset.companies) if args.all else list(dict.fromkeys(args.companies))
    if args.list:
        for key, row in sorted(dataset.companies.items()):
            print(f'{key}: {row["company_name"]} / {row["industry"]} / {row["operations_count"]} операций')
        return
    state = json.loads(args.state.read_text(encoding='utf-8')) if args.state.exists() else {}
    if state and (state['api_url'] != args.api_url.rstrip('/') or state['email'] != args.email):
        raise SeedError('This checkpoint belongs to another API/account; choose another --state')
    anchor_text = args.as_of or state.get('as_of') or (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
    if state and args.as_of and args.as_of != state['as_of']:
        raise SeedError('The checkpoint pins the date shift; choose another --state for another date')
    anchor = None if anchor_text == 'original' else date.fromisoformat(anchor_text)
    prepared = []
    for key in selected:
        raw, rows = dataset.statement(key)
        fingerprint = hashlib.sha256(raw).hexdigest()
        if key in state.get('companies', {}) and state['companies'][key]['fingerprint'] != fingerprint:
            raise SeedError('Dataset content changed; choose a separate checkpoint instead of mixing imports')
        chunks, as_of, balance, shift = statement_chunks(key, rows, anchor, fingerprint)
        original_last = max(date.fromisoformat(r['operation_date']) for r in rows)
        last_month = [r for r in rows if date.fromisoformat(r['operation_date']) > original_last - timedelta(days=30) and r['direction'] == 'Списание']
        monthly_out = sum((Decimal(money(r['amount'])) for r in last_month), Decimal(0))
        prepared.append((key, fingerprint, chunks, as_of, balance, shift, monthly_out))
        print(f'{key}: {len(rows)} операций, {len(chunks)} частей; дата выписки {as_of}, сдвиг {shift} дн.')
    if args.dry_run:
        return
    password = os.environ.get('PULS_DEMO_PASSWORD', '')
    if len(password) < 8:
        raise SeedError('Set PULS_DEMO_PASSWORD (8+ characters); it is not stored in the checkpoint')
    api = API(args.api_url)
    api.call('GET', '/readyz')
    api.authenticate(args.email, password)
    state = state or {'version': 1, 'api_url': api.origin, 'email': args.email, 'as_of': anchor_text, 'companies': {}}
    for key, fingerprint, chunks, as_of, balance, shift, monthly_out in prepared:
        name = 'Демо · ' + dataset.companies[key]['company_name']
        owned = api.call('GET', '/v1/me')['companies']
        previous_id = state['companies'].get(key, {}).get('company_id')
        company = next((c for c in owned if c['id'] == previous_id), None) or next((c for c in owned if c['name'] == name), None)
        if not company:
            meta = dataset.companies[key]
            # Anonymized dataset INNs need not have a valid official checksum.
            company = api.call('POST', '/v1/companies', {'name': name, 'legal_form': meta['legal_form'], 'industry': meta['industry']}, expected=(201,))
        cid, base = company['id'], '/v1/companies/' + company['id']
        state['companies'][key] = {'company_id': cid, 'fingerprint': fingerprint, 'shift_days': shift, 'data_as_of': as_of.isoformat()}
        save_state(args.state, state)
        added = duplicates = 0
        for chunk in chunks:
            report = api.upload(base, chunk)
            added += report['added']
            duplicates += report['duplicates']
        if not args.history_only:
            demo_plans(api, base, key, as_of, balance, monthly_out)
        api.idle(base)
        forecast = api.call('GET', base + '/forecast?horizon=30')
        if len(forecast['points']) != 30:
            raise SeedError('Forecast response did not contain 30 days')
        print(f'{name}: добавлено {added}, повторов {duplicates}; прогноз 30 дней готов.')
    print(f'Готово. Войдите на фронтенде как {args.email} с паролем из PULS_DEMO_PASSWORD. Состояние: {args.state}')


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    try:
        main()
    except (SeedError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f'Seed failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
