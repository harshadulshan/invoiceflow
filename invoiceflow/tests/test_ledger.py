import concurrent.futures
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from invoiceflow.ledger import Ledger, FIELDS, csv_bytes, money
from invoiceflow.analytics import ageing, due_schedule, summarize, worklist
from invoiceflow.demo import seed

TODAY = date.today()


def invoice(number='INV-1', amount='100.00', days=10):
    return dict(invoice_number=number, customer='Example Business', email='',
                issued_on=(TODAY-timedelta(days=150)).isoformat(),
                due_on=(TODAY-timedelta(days=days)).isoformat(), amount=amount)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ledger = Ledger(Path(self.temp.name)/'test.sqlite3')
        self.ledger.add_invoice(invoice())
        self.id = self.ledger.snapshot(TODAY)[0]['id']

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_money_and_invalid_amounts(self):
        self.assertEqual(money('0.29'), 29)
        for value in ['NaN', 'Infinity', '0', '-1', '1.001', 'abc', '1000000000', '1,000']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                money(value)

    def test_partial_and_complete_payment(self):
        self.ledger.pay(self.id, '33.33', TODAY.isoformat(), 'A')
        self.assertEqual(self.ledger.snapshot(TODAY)[0]['balance_cents'], 6667)
        self.ledger.pay(self.id, '66.67', TODAY.isoformat(), 'B')
        self.assertEqual(self.ledger.snapshot(TODAY)[0]['status'], 'Paid')

    def test_overpayment_rejected(self):
        with self.assertRaises(ValueError):
            self.ledger.pay(self.id, '100.01', TODAY.isoformat(), 'A')
        self.assertEqual(self.ledger.history(self.id, 'payments'), [])

    def test_duplicate_payment_reference(self):
        self.ledger.pay(self.id, '10', TODAY.isoformat(), 'A')
        with self.assertRaises(ValueError):
            self.ledger.pay(self.id, '10', TODAY.isoformat(), 'A')
        self.assertEqual(self.ledger.snapshot(TODAY)[0]['paid_cents'], 1000)

    def test_concurrent_payments_cannot_overpay(self):
        def attempt(ref):
            try:
                self.ledger.pay(self.id, '75', TODAY.isoformat(), ref)
                return True
            except ValueError:
                return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(attempt, ['A', 'B']))
        self.assertEqual(sum(results), 1)
        self.assertEqual(self.ledger.snapshot(TODAY)[0]['balance_cents'], 2500)

    def test_historical_balance_excludes_later_payment(self):
        self.ledger.pay(self.id, '25', TODAY.isoformat(), 'A')
        self.assertEqual(self.ledger.snapshot(TODAY-timedelta(days=1))[0]['balance_cents'], 10000)
        self.assertEqual(self.ledger.snapshot(TODAY)[0]['balance_cents'], 7500)
        self.assertEqual(self.ledger.snapshot(TODAY-timedelta(days=151)), [])

    def test_invalid_dates_and_missing_invoice(self):
        for when in [(TODAY+timedelta(days=1)).isoformat(), (TODAY-timedelta(days=151)).isoformat(), '2026-02-30']:
            with self.assertRaises(ValueError):
                self.ledger.pay(self.id, '1', when, 'A')
        with self.assertRaises(ValueError):
            self.ledger.pay(9999, '1', TODAY.isoformat(), 'B')

    def test_atomic_duplicate_import(self):
        rows = [invoice('INV-2'), invoice('INV-1')]
        with self.assertRaises(ValueError):
            self.ledger.add_many(rows)
        self.assertEqual(len(self.ledger.snapshot(TODAY)), 1)

    def test_atomic_invalid_import(self):
        rows = [invoice('INV-2'), invoice('INV-3', amount='bad')]
        with self.assertRaises(ValueError):
            self.ledger.add_many(rows)
        self.assertEqual(len(self.ledger.snapshot(TODAY)), 1)

    def test_csv_import_and_schema_validation(self):
        self.assertEqual(self.ledger.import_csv(csv_bytes([invoice('INV-2')], FIELDS)), 1)
        for data in [b'wrong,headers\nx,y\n', b'\xff', ','.join(FIELDS).encode(), b'x'*5_000_001]:
            with self.assertRaises(ValueError):
                self.ledger.import_csv(data)

    def test_csv_formula_escape(self):
        out = csv_bytes([{'customer': ' =1+1'}], ['customer']).decode('utf-8-sig')
        self.assertIn("' =1+1", out)

    def test_due_date_must_follow_issue(self):
        row = invoice('INV-2')
        row['due_on'] = '2000-01-01'
        with self.assertRaises(ValueError):
            self.ledger.add_invoice(row)

    def test_ageing_boundaries_and_due_today(self):
        for i in [0, 1, 30, 31, 60, 61, 90, 91]:
            self.ledger.add_invoice(invoice(f'DAY-{i}', days=i))
        rows = {r['invoice_number']: r for r in self.ledger.snapshot(TODAY)}
        expected = ['Current', '1–30', '1–30', '31–60', '31–60', '61–90', '61–90', '90+']
        for i, bucket in zip([0,1,30,31,60,61,90,91], expected):
            self.assertEqual(rows[f'DAY-{i}']['ageing'], bucket)
        self.assertEqual(rows['DAY-0']['status'], 'Open')

    def test_summary_and_schedule_reconcile(self):
        for i, days in enumerate([-40, -30, -8, -7, 0, 91]):
            self.ledger.add_invoice(invoice(f'OTHER-{i}', days=days))
        rows = self.ledger.snapshot(TODAY)
        total = summarize(rows)['outstanding']/100
        self.assertEqual(sum(r['balance'] for r in ageing(rows)), total)
        self.assertEqual(sum(r['balance'] for r in due_schedule(rows, TODAY)), total)

    def test_notes_and_worklist_priority(self):
        self.ledger.add_invoice(invoice('OLDER', days=100))
        self.ledger.add_note(self.id, 'Please call', TODAY.isoformat())
        self.assertEqual(worklist(self.ledger.snapshot(TODAY), TODAY)[0]['id'], self.id)
        self.assertEqual(self.ledger.history(self.id, 'notes')[0]['body'], 'Please call')
        with self.assertRaises(ValueError):
            self.ledger.add_note(99999, 'Missing')

    def test_backup_is_readable(self):
        target = Path(self.temp.name)/'backup.sqlite3'
        target.write_bytes(self.ledger.backup())
        with sqlite3.connect(target) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM invoices').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_persistence(self):
        again = Ledger(self.ledger.path)
        self.assertEqual(again.snapshot(TODAY)[0]['invoice_number'], 'INV-1')

    def test_demo_idempotent(self):
        fresh = Ledger(Path(self.temp.name)/'demo.sqlite3')
        self.assertTrue(seed(fresh, TODAY))
        self.assertFalse(seed(fresh, TODAY))
        self.assertEqual(len(fresh.snapshot(date.max)), 12)
        self.assertEqual(sum(r['status']=='Paid' for r in fresh.snapshot(TODAY)), 1)


if __name__ == '__main__':
    unittest.main()
