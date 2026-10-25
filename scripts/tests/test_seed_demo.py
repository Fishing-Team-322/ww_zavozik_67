"""Seeder data-contract tests; the optional live test runs against the CI stack."""
import contextlib
import csv
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'seed-demo.py'
spec = importlib.util.spec_from_file_location('seed_demo', SCRIPT)
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


def fixture(path, *, days=2):
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    meta = 'company_id;company_name;company_inn;legal_form;industry;first_operation_date;last_operation_date;operations_count\n'
    meta += f'C001;Seed test {uuid.uuid4()};0000000000;ООО;services;{end-timedelta(days=days-1)};{end};{days*2}\n'
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['company_id', 'operation_id', 'operation_date', 'amount', 'direction', 'counterparty_inn', 'counterparty_name', 'payment_purpose', 'balance_eod'])
    for i in range(days):
        dt = end - timedelta(days=days-i-1)
        for suffix, direction, amount, party in [('in', 'Поступление', '1000.01', 'Seed customer'), ('out', 'Списание', '900.00', 'Seed supplier')]:
            writer.writerow(['C001', f'{suffix}-{i}', dt, amount, direction, '0012345678', party, 'Fixture only', f'{100000+i*100}.01'])
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('case/companies.csv', meta.encode('utf-8-sig'))
        archive.writestr('case/statements/C001.csv', output.getvalue().encode('utf-8-sig'))
    return end


class SeedDataTests(unittest.TestCase):
    def test_zip_shift_preserves_cents_identifiers_and_unknown_balances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'case.zip'
            end = fixture(path)
            dataset = seed.Dataset(path)
            raw, rows = dataset.statement('C001')
            rows[0]['balance_eod'] = ''
            fingerprint = hashlib.sha256(raw).hexdigest()
            anchor = end - timedelta(days=10)
            chunks, as_of, balance, shift = seed.statement_chunks('C001', rows, anchor, fingerprint, limit=400)
            parsed = [r for chunk in chunks for r in csv.DictReader(io.StringIO(chunk.decode()), delimiter=';')]
            self.assertEqual(as_of, anchor)
            self.assertEqual(shift, -10)
            self.assertEqual(str(balance), '100100.01')
            self.assertEqual(len(parsed), 4)
            self.assertEqual(parsed[0]['amount'], '1000.01')
            self.assertEqual(parsed[0]['balance'], '')
            self.assertEqual(parsed[0]['counterparty_inn'], '0012345678')
            self.assertEqual(parsed[0]['date'], (anchor-timedelta(days=1)).isoformat())
            self.assertEqual(len({r['id'] for r in parsed}), 4)
            self.assertEqual(seed.statement_chunks('C001', rows, anchor, fingerprint, limit=400)[0], chunks)
            dataset.archive.close()

    def test_invalid_money_and_foreign_company_fail_before_any_api_write(self):
        for value in ['NaN', 'Infinity', '-0.01', '100.001']:
            with self.subTest(value=value), self.assertRaises(seed.SeedError):
                seed.money(value)
        self.assertEqual(seed.money('-100.01', signed=True), '-100.01')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'case.zip'
            fixture(path)
            dataset = seed.Dataset(path)
            with self.assertRaises(seed.SeedError):
                dataset.statement('C999')
            dataset.archive.close()

    def test_dry_run_does_not_create_an_account_or_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, state = Path(tmp)/'case.zip', Path(tmp)/'state.json'
            fixture(path)
            with patch.object(seed.API, 'call', side_effect=AssertionError('dry run contacted API')), contextlib.redirect_stdout(io.StringIO()):
                seed.main(['--dataset', str(path), '--companies', 'C001', '--state', str(state), '--dry-run'])
            self.assertFalse(state.exists())

    def test_remote_seeding_is_not_the_default_demo_operation(self):
        with self.assertRaises(seed.SeedError):
            seed.API('https://example.com')
        with self.assertRaises(seed.SeedError):
            seed.API('http://localhost:8080/?redirect=elsewhere')


@unittest.skipUnless(os.getenv('PULS_SEED_TEST_API_URL'), 'Set PULS_SEED_TEST_API_URL to an isolated local stack')
class SeedLiveTests(unittest.TestCase):
    def test_repeat_seed_keeps_financial_records_and_plans_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path, state = Path(tmp)/'case.zip', Path(tmp)/'state.json'
            fixture(path, days=120)
            email, password = f'seed-{uuid.uuid4()}@example.test', uuid.uuid4().hex
            args = ['--dataset', str(path), '--companies', 'C001', '--state', str(state), '--email', email, '--api-url', os.environ['PULS_SEED_TEST_API_URL']]
            with patch.dict(os.environ, {'PULS_DEMO_PASSWORD': password}), contextlib.redirect_stdout(io.StringIO()):
                seed.main(args)
                api = seed.API(os.environ['PULS_SEED_TEST_API_URL'])
                api.authenticate(email, password)
                base = '/v1/companies/' + api.call('GET', '/v1/me')['companies'][0]['id']

                def snapshot():
                    operations, cursor = [], ''
                    while True:
                        page = api.call('GET', base + '/operations?limit=200' + ('&cursor=' + cursor if cursor else ''))
                        operations.extend(page['items'])
                        cursor = page.get('next_cursor')
                        if not cursor:
                            break
                    return {'operations': {(r['id'], r['date'], r['amount']) for r in operations}, **{kind: {r['id'] for r in api.call('GET', base+'/'+kind)} for kind in ['invoices', 'contracts', 'events', 'scenarios']}}

                before = snapshot()
                seed.main(args)
                self.assertEqual(snapshot(), before)
                self.assertEqual(len(before['operations']), 240)
                self.assertEqual(len(before['invoices']), 3)
                self.assertEqual(len(before['contracts']), 1)
                self.assertEqual(len(before['scenarios']), 3)
                forecast = api.call('GET', base+'/forecast?horizon=30')
                self.assertEqual(len(forecast['points']), 30)
                checkpoint = state.read_text(encoding='utf-8')
                self.assertNotIn(password, checkpoint)
                self.assertNotIn('access_token', checkpoint)


if __name__ == '__main__':
    unittest.main()
