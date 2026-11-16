"""Synthetic, date-relative examples. No real customer information."""
from datetime import date, timedelta
from .ledger import Ledger


def seed(ledger: Ledger, today: date):
    if ledger.snapshot(date.max):
        return False
    customers = [('Lanka Design Studio', 'accounts@example.com'), ('Hill Country Foods', 'finance@example.com'),
                 ('Coastal Print Works', ''), ('Green Leaf Supplies', ''), ('Metro IT Services', '')]
    offsets = [-110, -75, -45, -20, -4, 0, 4, 12, 25, 45, -12, -35]
    amounts = [125000, 86400, 15750, 48250, 96500, 31500, 78000, 62500, 21900, 144000, 38000, 55000]
    for i, (offset, amount) in enumerate(zip(offsets, amounts), 1):
        customer, email = customers[(i-1) % len(customers)]
        due = today + timedelta(days=offset)
        ledger.add_invoice(dict(invoice_number=f'DEMO-{i:03}', customer=customer, email=email,
                                issued_on=(due-timedelta(days=30)).isoformat(), due_on=due.isoformat(), amount=str(amount)))
    ids = {r['invoice_number']: r['id'] for r in ledger.snapshot(date.max)}
    ledger.pay(ids['DEMO-003'], '5000', (today-timedelta(days=40)).isoformat(), 'DEMO-BANK-001')
    ledger.pay(ids['DEMO-011'], '38000', (today-timedelta(days=5)).isoformat(), 'DEMO-BANK-002')
    ledger.add_note(ids['DEMO-001'], 'Synthetic example: customer asked for a copy of the invoice.', today.isoformat())
    ledger.add_note(ids['DEMO-004'], 'Synthetic example: follow up next week.', (today+timedelta(days=7)).isoformat())
    return True
