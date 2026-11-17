"""Local invoice ledger. Money is stored as integer cents; writes are atomic."""
from __future__ import annotations

import csv
import io
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = ['invoice_number', 'customer', 'email', 'issued_on', 'due_on', 'amount']


def money(value: str) -> int:
    """Parse an exact positive currency amount, rejecting rounding and non-finite input."""
    try:
        amount = Decimal(str(value).strip())
        if not amount.is_finite() or amount <= 0 or amount > Decimal('999999999.99'):
            raise ValueError('Amount must be between 0.01 and 999999999.99.')
        if amount != amount.quantize(Decimal('.01')):
            raise ValueError('Use at most two decimal places.')
        return int(amount * 100)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError('Enter a valid amount, for example 12500.50.') from exc


def iso(value: str) -> str:
    parsed = date.fromisoformat(str(value))
    if parsed.isoformat() != value:
        raise ValueError('Dates must use YYYY-MM-DD.')
    return value


def clean(row: dict) -> dict:
    result = {key: str(row.get(key) or '').strip() for key in FIELDS}
    if not result['invoice_number'] or len(result['invoice_number']) > 80:
        raise ValueError('Invoice number is required (maximum 80 characters).')
    if not result['customer'] or len(result['customer']) > 150:
        raise ValueError('Customer is required (maximum 150 characters).')
    if len(result['email']) > 254 or (result['email'] and ('@' not in result['email'] or '\n' in result['email'])):
        raise ValueError('Use a valid contact email or leave it empty.')
    iso(result['issued_on'])
    iso(result['due_on'])
    if result['due_on'] < result['issued_on']:
        raise ValueError('Due date cannot be before issue date.')
    result['amount_cents'] = money(result.pop('amount'))
    return result


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS invoices (
              id INTEGER PRIMARY KEY, invoice_number TEXT NOT NULL UNIQUE,
              customer TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
              issued_on TEXT NOT NULL, due_on TEXT NOT NULL,
              amount_cents INTEGER NOT NULL CHECK(amount_cents > 0));
            CREATE TABLE IF NOT EXISTS payments (
              id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
              paid_on TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
              reference TEXT NOT NULL, created_at TEXT NOT NULL,
              UNIQUE(invoice_id, reference));
            CREATE TABLE IF NOT EXISTS notes (
              id INTEGER PRIMARY KEY, invoice_id INTEGER NOT NULL REFERENCES invoices(id),
              body TEXT NOT NULL, next_followup TEXT, created_at TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add_invoice(self, row: dict) -> None:
        self.add_many([row])

    def add_many(self, rows: list[dict]) -> int:
        validated = [clean(row) for row in rows]
        with self.connect() as db:
            try:
                db.executemany('''INSERT INTO invoices
                  (invoice_number,customer,email,issued_on,due_on,amount_cents)
                  VALUES (:invoice_number,:customer,:email,:issued_on,:due_on,:amount_cents)''', validated)
            except sqlite3.IntegrityError as exc:
                raise ValueError('Duplicate invoice number. Nothing in this batch was imported.') from exc
        return len(validated)

    def import_csv(self, content: bytes) -> int:
        if len(content) > 5_000_000:
            raise ValueError('CSV must be smaller than 5 MB.')
        try:
            reader = csv.DictReader(io.StringIO(content.decode('utf-8-sig')))
            if reader.fieldnames != FIELDS:
                raise ValueError('CSV headers must be exactly: ' + ','.join(FIELDS))
            rows = list(reader)
        except UnicodeDecodeError as exc:
            raise ValueError('Save the CSV using UTF-8 encoding.') from exc
        if not rows or len(rows) > 10000:
            raise ValueError('Import between 1 and 10,000 invoices.')
        if any(None in row for row in rows):
            raise ValueError('A CSV row has more columns than the header.')
        return self.add_many(rows)

    def pay(self, invoice_id: int, amount: str, paid_on: str, reference: str) -> None:
        cents = money(amount)
        iso(paid_on)
        reference = reference.strip()
        if not reference or len(reference) > 120:
            raise ValueError('A payment reference is required (maximum 120 characters).')
        if paid_on > date.today().isoformat():
            raise ValueError('A received payment cannot be dated in the future.')
        with self.connect() as db:
            # Lock before checking the balance, so concurrent writers cannot overpay.
            db.execute('BEGIN IMMEDIATE')
            invoice = db.execute('SELECT * FROM invoices WHERE id=?', (invoice_id,)).fetchone()
            if invoice is None:
                raise ValueError('Invoice does not exist.')
            if paid_on < invoice['issued_on']:
                raise ValueError('Payment cannot be before the invoice was issued.')
            paid = db.execute('SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE invoice_id=?', (invoice_id,)).fetchone()[0]
            if cents > invoice['amount_cents'] - paid:
                raise ValueError('Payment exceeds the remaining balance.')
            try:
                db.execute('INSERT INTO payments(invoice_id,paid_on,amount_cents,reference,created_at) VALUES(?,?,?,?,?)',
                           (invoice_id, paid_on, cents, reference, datetime.now(timezone.utc).isoformat()))
            except sqlite3.IntegrityError as exc:
                raise ValueError('This payment reference already exists for that invoice.') from exc

    def add_note(self, invoice_id: int, body: str, next_followup: str | None = None):
        body = body.strip()
        if not body or len(body) > 2000:
            raise ValueError('Enter a note of 1 to 2,000 characters.')
        if next_followup:
            iso(next_followup)
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM invoices WHERE id=?', (invoice_id,)).fetchone():
                raise ValueError('Invoice does not exist.')
            db.execute('INSERT INTO notes(invoice_id,body,next_followup,created_at) VALUES(?,?,?,?)',
                       (invoice_id, body, next_followup, datetime.now(timezone.utc).isoformat()))

    def snapshot(self, as_of: date) -> list[dict]:
        """Historical balance uses payment dates; later notes are current workflow metadata."""
        with self.connect() as db:
            rows = db.execute('''SELECT i.*, COALESCE(p.paid_cents,0) AS paid_cents,
                (SELECT next_followup FROM notes WHERE invoice_id=i.id ORDER BY id DESC LIMIT 1) AS next_followup
                FROM invoices i LEFT JOIN
                (SELECT invoice_id,SUM(amount_cents) AS paid_cents FROM payments WHERE paid_on<=? GROUP BY invoice_id) p
                ON i.id=p.invoice_id WHERE i.issued_on<=?''', (as_of.isoformat(), as_of.isoformat())).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['balance_cents'] = item['amount_cents'] - item['paid_cents']
            days = max(0, (as_of - date.fromisoformat(item['due_on'])).days)
            item['days_overdue'] = days
            item['status'] = 'Paid' if item['balance_cents'] == 0 else ('Overdue' if days else 'Open')
            item['ageing'] = ('Current' if days == 0 else '1–30' if days <= 30 else '31–60' if days <= 60 else '61–90' if days <= 90 else '90+')
            result.append(item)
        return sorted(result, key=lambda r: (-r['days_overdue'], -r['balance_cents'], r['invoice_number']))

    def history(self, invoice_id: int, table: str) -> list[dict]:
        if table not in ('notes', 'payments'):
            raise ValueError('Unknown history type.')
        with self.connect() as db:
            return [dict(r) for r in db.execute(f'SELECT * FROM {table} WHERE invoice_id=? ORDER BY id DESC', (invoice_id,))]

    def backup(self) -> bytes:
        """Produce a consistent SQLite backup through SQLite's backup API."""
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'ledger.sqlite3'
            with self.connect() as source, sqlite3.connect(target) as dest:
                source.backup(dest)
            return target.read_bytes()


def csv_bytes(rows: list[dict], fields: list[str]) -> bytes:
    """Escape spreadsheet formula prefixes in user-controlled text exports."""
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        safe = {k: ("'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v) for k, v in row.items()}
        writer.writerow(safe)
    return stream.getvalue().encode('utf-8-sig')
