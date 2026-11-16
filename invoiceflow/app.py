"""Run with: python -m streamlit run app.py"""
import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from invoiceflow.analytics import ageing, due_schedule, reminder, summarize, worklist
from invoiceflow.demo import seed
from invoiceflow.ledger import FIELDS, Ledger, csv_bytes

st.set_page_config(page_title='InvoiceFlow · Receivables', page_icon='◈', layout='wide')
st.markdown('''<style>
.stApp {background: #f5f7fb; color: #142a43;}
h1,h2,h3 {letter-spacing:-.035em;}
[data-testid="stMetric"] {background:white; border:1px solid #e0e7ef; border-radius:12px; padding:18px;}
[data-testid="stSidebar"] {background:#e9eff7;}
.block-container {padding-top:2.5rem; max-width:1500px;}
</style>''', unsafe_allow_html=True)

with st.sidebar:
    st.title('◈ InvoiceFlow')
    st.caption('A clearer view of money owed.')
    mode = st.radio('Workspace', ['Demo business', 'My business'])
    st.divider()
    st.caption('REPORTING')
    as_of = st.date_input('Balances as of', value=date.today())
    query = st.text_input('Find customer or invoice', placeholder='Search…')
    state = st.multiselect('Invoice status', ['Open', 'Overdue', 'Paid'])
    st.divider()
    st.caption('Currency: LKR · two decimal places')
    st.caption('Local single-user tool. Use a private computer and keep regular backups.')

root = Path(os.getenv('INVOICEFLOW_DATA_DIR', str(Path(__file__).parent / 'data')))
ledger = Ledger(root / ('demo.sqlite3' if mode == 'Demo business' else 'business.sqlite3'))
if mode == 'Demo business':
    seed(ledger, date.today())

st.caption('SMALL BUSINESS / ACCOUNTS RECEIVABLE')
st.title('Get paid. Stay organised.')
st.write('Track outstanding invoices, record receipts, and know which customer to follow up with next.')
if mode == 'Demo business':
    st.info('Demo workspace · Fictional LKR invoices. Your own business uses a separate database.')
if 'notice' in st.session_state:
    st.success(st.session_state.pop('notice'))

rows = ledger.snapshot(as_of)
filtered = [r for r in rows if (not query or query.casefold() in (r['customer']+' '+r['invoice_number']).casefold()) and (not state or r['status'] in state)]
summary = summarize(filtered)
a, b, c, d = st.columns(4)
a.metric('Outstanding · LKR', f"{summary['outstanding']/100:,.2f}")
b.metric('Overdue · LKR', f"{summary['overdue']/100:,.2f}")
c.metric('Received by report date · LKR', f"{summary['received']/100:,.2f}")
d.metric('Unpaid invoices', summary['open_count'])
st.caption(f'{len(filtered)} of {len(rows)} invoices · Metrics, charts and exports follow the selected filters. Due today is current, not overdue.')


def display_rows(items):
    return [dict(Invoice=r['invoice_number'], Customer=r['customer'], Due=r['due_on'],
                 Amount=r['amount_cents']/100, Received=r['paid_cents']/100,
                 Balance=r['balance_cents']/100, Status=r['status'], Days_overdue=r['days_overdue']) for r in items]


def done(message):
    st.session_state['notice'] = message
    st.rerun()


def render_table(items):
    if items:
        st.dataframe(pd.DataFrame(display_rows(items)), hide_index=True, width='stretch',
                     column_config={k: st.column_config.NumberColumn(k+' · LKR', format='%.2f') for k in ['Amount', 'Received', 'Balance']})
    else:
        st.info('No invoices match this view.')


overview, invoices, collect, reports, data = st.tabs(['Overview', 'Invoices & payments', 'Collection worklist', 'Reports', 'Import & backup'])
with overview:
    left, right = st.columns([1.15, 1])
    with left:
        st.subheader('Where balances are ageing')
        st.caption('Unpaid value by days after the due date · LKR')
        st.bar_chart(pd.DataFrame(ageing(filtered)).set_index('bucket'), color='#0d9488')
    with right:
        st.subheader('Contractual due schedule')
        st.caption('When unpaid invoices fall due. This is not a cash-receipt forecast.')
        st.dataframe(pd.DataFrame(due_schedule(filtered, as_of)), hide_index=True, width='stretch',
                     column_config={'balance': st.column_config.NumberColumn('Balance · LKR', format='%.2f')})
        st.write('**Next action**')
        pending = worklist(filtered, as_of)
        if pending:
            next_item = pending[0]
            st.write(f"{next_item['invoice_number']} · {next_item['customer']}")
            st.caption(f"{next_item['reason']} · LKR {next_item['balance_cents']/100:,.2f} outstanding")
        else:
            st.success('No unpaid invoices in this view.')
    st.subheader('Invoice register')
    render_table(filtered)

with invoices:
    with st.expander('Create an invoice', expanded=not rows):
        with st.form('new_invoice', clear_on_submit=True):
            c1, c2 = st.columns(2)
            number = c1.text_input('Invoice number', max_chars=80)
            customer = c2.text_input('Customer name', max_chars=150)
            email = c1.text_input('Contact email (optional)')
            amount = c2.text_input('Invoice total · LKR', placeholder='12500.50')
            issued = c1.date_input('Issue date', value=date.today())
            due = c2.date_input('Due date', value=date.today())
            st.caption('Record the final invoice total, including any applicable taxes. This app does not calculate taxes.')
            if st.form_submit_button('Save invoice', type='primary'):
                try:
                    ledger.add_invoice(dict(invoice_number=number, customer=customer, email=email,
                                            amount=amount, issued_on=issued.isoformat(), due_on=due.isoformat()))
                    done('Invoice saved.')
                except ValueError as exc:
                    st.error(str(exc))
    render_table(filtered)
    # Writes always use today's balance, even when the report date is historical.
    current = ledger.snapshot(date.today())
    if current:
        selected_id = st.selectbox('Select invoice to view or record a payment', [r['id'] for r in current],
                                   format_func=lambda value: next(f"{r['invoice_number']} · {r['customer']} · LKR {r['balance_cents']/100:,.2f} remaining today" for r in current if r['id'] == value))
        item = next(r for r in current if r['id'] == selected_id)
        st.caption('Payments below show all recorded receipts. New payments use the current balance, independently of the report-date filter.')
        with st.form('payment', clear_on_submit=True):
            p1, p2, p3 = st.columns(3)
            payment = p1.text_input('Amount received · LKR')
            paid_on = p2.date_input('Payment date', max_value=date.today())
            reference = p3.text_input('Unique payment reference')
            if st.form_submit_button('Record payment', disabled=item['balance_cents'] == 0):
                try:
                    ledger.pay(selected_id, payment, paid_on.isoformat(), reference)
                    done('Payment recorded.')
                except ValueError as exc:
                    st.error(str(exc))
        history = ledger.history(selected_id, 'payments')
        if history:
            st.dataframe(pd.DataFrame([{'Date': p['paid_on'], 'Amount · LKR': p['amount_cents']/100,
                                        'Reference': p['reference'], 'Recorded at (UTC)': p['created_at']} for p in history]), hide_index=True, width='stretch')

with collect:
    st.subheader('Your next conversations')
    st.write('Due follow-ups come first, then the oldest overdue invoices, then the largest balance. This is a transparent rule, not an AI risk score.')
    st.caption('Notes and follow-up dates always reflect the current workflow, including in historical report views.')
    pending = worklist(filtered, as_of)
    if pending:
        st.dataframe(pd.DataFrame([{'Invoice': r['invoice_number'], 'Customer': r['customer'],
                                   'Balance · LKR': r['balance_cents']/100, 'Days overdue': r['days_overdue'],
                                   'Reason': r['reason'], 'Next follow-up': r['next_followup']} for r in pending]), hide_index=True, width='stretch')
        selected = st.selectbox('Invoice to follow up', [r['id'] for r in pending],
                                format_func=lambda value: next(r['invoice_number']+' · '+r['customer'] for r in pending if r['id'] == value))
        item = next(r for r in pending if r['id'] == selected)
        left, right = st.columns(2)
        with left:
            st.caption('Draft only · Review the text before using it. Nothing is sent automatically.')
            draft = reminder(item, 'LKR')
            st.text_area('Payment reminder', draft, height=250, key=f'draft-{selected}-{as_of}')
            st.download_button('Download reminder draft', draft, f"reminder-{selected}.txt")
        with right:
            with st.form('note', clear_on_submit=True):
                body = st.text_area('Conversation note', placeholder='Customer confirmed expected payment date…', max_chars=2000)
                followup = st.date_input('Next follow-up date')
                if st.form_submit_button('Save follow-up'):
                    try:
                        ledger.add_note(selected, body, followup.isoformat())
                        done('Follow-up saved.')
                    except ValueError as exc:
                        st.error(str(exc))
            for note in ledger.history(selected, 'notes'):
                st.caption(f"{note['created_at'][:10]} · Next follow-up: {note['next_followup'] or 'None'}")
                st.text(note['body'])
    else:
        st.info('No unpaid invoices match your filters.')

with reports:
    st.subheader('Customer balances')
    if filtered:
        frame = pd.DataFrame(filtered)
        grouped = frame.groupby('customer')[['amount_cents', 'paid_cents', 'balance_cents']].sum()/100
        grouped.columns = ['Invoiced · LKR', 'Received · LKR', 'Outstanding · LKR']
        st.dataframe(grouped.sort_values('Outstanding · LKR', ascending=False), width='stretch')
        st.download_button('Download customer report', csv_bytes(grouped.reset_index().to_dict('records'), ['customer', *grouped.columns]), 'customer-balances.csv', 'text/csv')
    exported = display_rows(filtered)
    st.download_button('Download invoice report', csv_bytes(exported, ['Invoice','Customer','Due','Amount','Received','Balance','Status','Days_overdue']), 'invoice-report.csv', 'text/csv')
    buckets = ageing(filtered)
    st.download_button('Download ageing report', csv_bytes(buckets, ['bucket', 'balance']), 'ageing-report.csv', 'text/csv')
    st.caption('Reports contain only invoices issued on or before the report date and receipts dated on or before that date. No currency conversion is performed.')

with data:
    st.subheader('Bring your invoices')
    st.write('Upload UTF-8 CSV files with the exact six-column template below. Amounts use a decimal point, without currency symbols or thousands separators.')
    st.download_button('Download import template', csv_bytes([dict(zip(FIELDS, ['INV-001','Example Customer','accounts@example.com',date.today().isoformat(),date.today().isoformat(),'12500.50']))], FIELDS), 'invoice-template.csv', 'text/csv')
    upload = st.file_uploader('Invoices CSV · up to 5 MB', type=['csv'])
    if upload:
        st.caption('Duplicate invoice numbers or invalid rows reject the whole file. Existing invoices are never overwritten.')
        if st.button('Import invoices', type='primary'):
            try:
                count = ledger.import_csv(upload.getvalue())
                done(f'Imported {count} invoices.')
            except ValueError as exc:
                st.error(str(exc))
    st.divider()
    st.subheader('Keep a backup')
    st.write('Download a consistent copy of this workspace. To restore: stop the app, copy the backup into the data directory using the correct database filename, then restart.')
    if st.button('Prepare database backup'):
        st.download_button('Download SQLite backup', ledger.backup(), 'demo.sqlite3' if mode == 'Demo business' else 'business.sqlite3', 'application/vnd.sqlite3')
    st.caption('The database contains customer contacts and payment records. Keep backups private. Demo and business data are separate.')
