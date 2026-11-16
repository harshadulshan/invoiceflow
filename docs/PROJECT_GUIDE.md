# Project guide

## Intended user

A small service business, supplier or freelancer with one accounts assistant who already issues invoices but tracks unpaid totals manually.

## Pain point and feasible solution

The pain is losing track of partial receipts and follow-up conversations. The feasible first version records invoices, subtracts validated receipts, calculates ageing and gives the user a clear next-action list. Data stays in a local SQLite file; no paid service or training dataset is needed.

This project demonstrates a working business workflow. It has not been evaluated with real businesses, and no claim of improved collection rates is made.

## Acceptance criteria implemented

- A new business workspace starts empty and persists after restart.
- A partial payment reduces the unpaid balance by exactly that amount.
- A fully settled invoice is marked paid.
- Duplicate references and excess receipts are rejected.
- A bad import leaves no partly imported batch.
- A historical report excludes later receipts and future-issued invoices.
- Due dates, ageing totals and the invoice register reconcile.
- Notes and follow-up dates appear against the correct invoice.
- The user can export reports and back up the database.

## Interview demonstration

1. Describe the spreadsheet problem in one sentence.
2. Create an invoice for LKR 10,000 in My business.
3. Record an LKR 2,500 payment; show LKR 7,500 outstanding.
4. Explain integer cents and why money should not use binary floating-point arithmetic.
5. Show an overdue demo invoice, a follow-up note and the collection list.
6. Explain why a due schedule is not a reliable cash-flow forecast.
7. Run the tests and show the concurrent-payment and atomic-import checks.

## Trade-offs you can explain

SQLite keeps setup simple and works well for a local single-user MVP. It does not provide user authentication or a hosted multi-user service. Deterministic worklist rules are visible and require no labelled historical collection outcomes. They should not be described as an AI model.

Financial snapshots are date-based, not complete point-in-time audit reconstruction. A backdated receipt entered today changes earlier date reports. Notes are intentionally current workflow metadata.

## Next useful improvements

1. Validate the workflow with three local businesses and document their feedback.
2. Add credit notes and auditable reversals before handling accounting corrections.
3. Add invoice attachments and customer identities separate from display names.
4. Add PostgreSQL, authentication, organisation isolation and permissions for a hosted version.
5. Add tested bank-statement reconciliation, with explicit user confirmation of matches.

## Portfolio wording

“Built a Python and Streamlit receivables tracker with SQLite persistence, exact-cent payment validation, historical balance reporting, atomic CSV imports, collection follow-ups and automated workflow tests.”

Understand and adapt the implementation before presenting it. Describe the scope honestly; do not claim real users, production deployment or collection improvements without evidence.
