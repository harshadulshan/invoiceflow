"""Transparent, deterministic reports; no predictive collection claims."""
from datetime import date, timedelta

BUCKETS = ['Current', '1–30', '31–60', '61–90', '90+']


def summarize(rows):
    return {
        'invoiced': sum(r['amount_cents'] for r in rows),
        'received': sum(r['paid_cents'] for r in rows),
        'outstanding': sum(r['balance_cents'] for r in rows),
        'overdue': sum(r['balance_cents'] for r in rows if r['days_overdue'] > 0),
        'open_count': sum(r['balance_cents'] > 0 for r in rows),
    }


def ageing(rows):
    return [{'bucket': b, 'balance': sum(r['balance_cents'] for r in rows if r['ageing'] == b) / 100} for b in BUCKETS]


def due_schedule(rows, as_of: date):
    """Outstanding contractual dues, not an estimate of when customers will pay."""
    buckets = ['Overdue / due today', 'Next 7 days', '8–30 days', 'Later']
    totals = dict.fromkeys(buckets, 0)
    for row in rows:
        days = (date.fromisoformat(row['due_on']) - as_of).days
        bucket = buckets[0] if days <= 0 else buckets[1] if days <= 7 else buckets[2] if days <= 30 else buckets[3]
        totals[bucket] += row['balance_cents'] / 100
    return [{'period': k, 'balance': v} for k, v in totals.items()]


def worklist(rows, as_of: date):
    result = []
    for row in rows:
        if row['balance_cents'] <= 0:
            continue
        followup = row.get('next_followup')
        reason = ('Follow-up due' if followup and followup <= as_of.isoformat() else
                  '90+ days overdue' if row['days_overdue'] > 90 else
                  'Overdue' if row['days_overdue'] else 'Upcoming due date')
        result.append(dict(row, reason=reason, followup_due=bool(followup and followup <= as_of.isoformat())))
    return sorted(result, key=lambda r: (not r['followup_due'], -r['days_overdue'], -r['balance_cents'], r['invoice_number']))


def reminder(row, currency):
    return (f"Subject: Payment reminder — {row['invoice_number']}\n\n"
            f"Hello {row['customer']},\n\n"
            f"Our records show an outstanding balance of {currency} {row['balance_cents']/100:,.2f} "
            f"for invoice {row['invoice_number']}, due on {row['due_on']}.\n\n"
            "Could you please confirm the payment status or let us know your expected payment date? "
            "If payment has already been made, please share the reference so we can update our records.\n\n"
            "Thank you,\nAccounts team")
