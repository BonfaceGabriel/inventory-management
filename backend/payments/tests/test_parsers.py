from django.test import TestCase
from payments.parsers import parse_mpesa_sms


class MpesaParserTest(TestCase):
    def test_parse_till_sms(self):
        raw = "JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000. New balance: KES 50,000.00. Transaction ID: QWERTY1234 on 20/05/2024 at 18:10"
        result = parse_mpesa_sms(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result['sender_name'], 'JOHN DOE')
        self.assertEqual(result['amount'], 1200.00)
        self.assertEqual(result['gateway_type'], 'till')
        self.assertEqual(result['tx_id'], 'QWERTY1234')

    def test_parse_paybill_sms(self):
        raw = "JANE DOE paid KES 2,500.00 to BUSINESS NUMBER 123456. Account: INV-001. New balance: KES 100,000.00. Transaction ID: PAYBILL001 on 20/05/2024 at 14:30"
        result = parse_mpesa_sms(raw)
        self.assertIsNotNone(result)
        self.assertIn(result['gateway_type'], ['paybill', 'till'])

    def test_parse_customer_name_with_multiple_parts(self):
        raw = "JOHN MICHAEL DOE sent KES 500.00 to TILL NUMBER 555000. New balance: KES 30,000.00. Transaction ID: TXMULTI01 on 21/05/2024 at 10:00"
        result = parse_mpesa_sms(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result['sender_name'], 'JOHN MICHAEL DOE')

    def test_parse_unparseable_message(self):
        result = parse_mpesa_sms("This is not an M-PESA message")
        self.assertIsNone(result)

    def test_parse_empty_string(self):
        result = parse_mpesa_sms("")
        self.assertIsNone(result)

    def test_parse_none(self):
        result = parse_mpesa_sms(None)
        self.assertIsNone(result)

    def test_parse_amount_without_commas(self):
        raw = "TEST USER sent KES 1000.00 to TILL NUMBER 555000. New balance: KES 10000.00. Transaction ID: TXNOCOMMA on 21/05/2024 at 11:00"
        result = parse_mpesa_sms(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result['amount'], 1000.00)

    def test_parse_large_amount(self):
        raw = "RICH USER sent KES 150,000.00 to TILL NUMBER 555000. New balance: KES 500,000.00. Transaction ID: LARGETX01 on 21/05/2024 at 12:00"
        result = parse_mpesa_sms(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result['amount'], 150000.00)

    def test_parse_decimals_in_amount(self):
        raw = "PRECISE USER sent KES 1,234.50 to TILL NUMBER 555000. New balance: KES 10,000.00. Transaction ID: DECTX01 on 21/05/2024 at 13:00"
        result = parse_mpesa_sms(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result['amount'], 1234.50)

    def test_parse_different_till_formats(self):
        raw = "CUSTOMER A confirmed KES 800.00 sent to TILL 555000. New balance: KES 20,000.00. Transaction ID: TILLVAR01 on 21/05/2024 at 14:00"
        result = parse_mpesa_sms(raw)
        self.assertIsNotNone(result)

    def test_parse_returns_confidence(self):
        raw = "JOHN DOE sent KES 1,200.00 to TILL NUMBER 555000. New balance: KES 50,000.00. Transaction ID: CONFID01 on 20/05/2024 at 18:10"
        result = parse_mpesa_sms(raw)
        self.assertIsNotNone(result)
        self.assertGreater(result['confidence'], 0)

    def test_parse_withdrawn_transaction(self):
        raw = "Withdraw KES 500.00 from AGENT. New balance: KES 10,000.00. Transaction ID: WITHDRAW01 on 21/05/2024 at 15:00"
        result = parse_mpesa_sms(raw)
        self.assertIsNone(result)

    def test_parse_airtime_transaction(self):
        raw = "You bought KES 100.00 of airtime for 0712345678. Transaction ID: AIRTIME01 on 21/05/2024 at 16:00"
        result = parse_mpesa_sms(raw)
        self.assertIsNone(result)
