"""UI interaction checks using Streamlit's supported test harness."""
import os
import tempfile
import unittest
from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1]/'app.py'


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('INVOICEFLOW_DATA_DIR')
        os.environ['INVOICEFLOW_DATA_DIR'] = self.temp.name
        self.app = AppTest.from_file(str(APP)).run(timeout=30)

    def tearDown(self):
        if self.old is None:
            os.environ.pop('INVOICEFLOW_DATA_DIR', None)
        else:
            os.environ['INVOICEFLOW_DATA_DIR'] = self.old
        self.temp.cleanup()

    def test_demo_loads_all_tabs(self):
        self.assertFalse(self.app.exception)
        self.assertEqual(len(self.app.tabs), 5)
        self.assertEqual(self.app.metric[3].value, '10')  # one future-issued invoice and one paid invoice

    def test_empty_business_and_create_invoice(self):
        self.app.radio[0].set_value('My business').run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[3].value, '0')
        values = {'Invoice number': 'TEST-001', 'Customer name': 'Test Customer', 'Invoice total · LKR': '2500.50'}
        for field in self.app.text_input:
            if field.label in values:
                field.set_value(values[field.label])
        next(b for b in self.app.button if b.label == 'Save invoice').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, '2,500.50')
        for field in self.app.text_input:
            if field.label == 'Amount received · LKR': field.set_value('500.50')
            if field.label == 'Unique payment reference': field.set_value('TEST-PAY-001')
        next(b for b in self.app.button if b.label == 'Record payment').click().run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, '2,000.00')

    def test_search_empty_result(self):
        next(f for f in self.app.text_input if f.label == 'Find customer or invoice').set_value('no such customer').run()
        self.assertFalse(self.app.exception)
        self.assertEqual(self.app.metric[0].value, '0.00')

    def test_followup_note(self):
        self.app.text_area[1].set_value('Customer asked us to call tomorrow')
        next(b for b in self.app.button if b.label == 'Save follow-up').click().run()
        self.assertFalse(self.app.exception)
        self.assertTrue(any('Follow-up saved.' in s.value for s in self.app.success))
