import json
from pathlib import Path
from django.test import TestCase
from payments.parsers import parse_mpesa_sms
from datetime import datetime

class MpesaParserTests(TestCase):

    def test_parser_with_fixtures(self):
        """
        Test the M-Pesa parser with a set of fixture messages.
        """
        fixture_path = Path(__file__).parent.parent / 'fixtures' / 'sample_messages.json'
        with open(fixture_path, 'r') as f:
            fixtures = json.load(f)

        for fixture in fixtures:
            text = fixture['text']
            expected = fixture['expected']
            
            parsed_data = parse_mpesa_sms(text)

            if 'timestamp' in expected:
                expected['timestamp'] = datetime.fromisoformat(expected['timestamp'])

            # The raw_text is added to the parsed_data on failure, so we need to handle that
            if 'raw_text' in parsed_data and 'raw_text' not in expected:
                del parsed_data['raw_text']

            self.assertEqual(parsed_data, expected)
