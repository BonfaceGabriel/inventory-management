import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Regex patterns for different M-Pesa messages
# Focusing on messages received by businesses

PATTERNS = [
    {
        'name': 'buy_goods_till',
        'regex': r'(?P<tx_id>\w+) Confirmed\. You have received Ksh(?P<amount>[\d,]+\.\d{2}) from (?P<sender_name>[A-Z\s]+) (?P<sender_phone>\d+) on (?P<date>\d{1,2}/\d{1,2}/\d{2,4}) at (?P<time>\d{1,2}:\d{2} [AP]M)\. New M-PESA balance is Ksh[\d,]+\.\d{2}\.',
        'parser': 'parse_standard_receipt'
    },
    {
        'name': 'paybill_received',
        'regex': r'(?P<tx_id>\w+) Confirmed\. You have received Ksh(?P<amount>[\d,]+\.\d{2}) from (?P<sender_name>[A-Z\s]+) (?P<sender_phone>\d+) on (?P<date>\d{1,2}/\d{1,2}/\d{2,4}) at (?P<time>\d{1,2}:\d{2} [AP]M) for account (?P<account_number>\w+)\. New M-PESA balance is Ksh[\d,]+\.\d{2}\.',
        'parser': 'parse_paybill_receipt'
    },
    # Fallback for slight variations
    {
        'name': 'buy_goods_till_variant',
        'regex': r'(?P<tx_id>\w+) Confirmed\. Ksh(?P<amount>[\d,]+\.\d{2}) received from (?P<sender_name>[A-Z\s]+) - (?P<sender_phone>\d+) on (?P<date>\d{1,2}/\d{1,2}/\d{2,4}) at (?P<time>\d{1,2}:\d{2} [AP]M)\.',
        'parser': 'parse_standard_receipt'
    },
]

def normalize_amount(amount_str):
    """Removes commas and converts to float."""
    return float(amount_str.replace(',', ''))

def normalize_timestamp(date_str, time_str):
    """Combines date and time strings and converts to a datetime object."""
    # Assuming the year is in the 21st century for 2-digit years
    if len(date_str.split('/')[-1]) == 2:
        date_str = date_str[:-2] + '20' + date_str[-2:]
    
    dt_str = f'{date_str} {time_str}'
    return datetime.strptime(dt_str, '%d/%m/%Y %I:%M %p')

def parse_standard_receipt(match):
    data = match.groupdict()
    return {
        'tx_id': data['tx_id'],
        'amount': normalize_amount(data['amount']),
        'sender_name': data['sender_name'].strip(),
        'sender_phone': data['sender_phone'],
        'timestamp': normalize_timestamp(data['date'], data['time']),
        'gateway_type': 'till',
        'confidence': 0.9
    }

def parse_paybill_receipt(match):
    data = match.groupdict()
    parsed_data = parse_standard_receipt(match)
    parsed_data['gateway_type'] = 'paybill'
    parsed_data['destination_number'] = data['account_number']
    parsed_data['confidence'] = 0.95
    return parsed_data

def parse_mpesa_sms(raw_text):
    """
    Parses an M-Pesa SMS message and returns a structured dictionary.
    """
    for pattern in PATTERNS:
        match = re.match(pattern['regex'], raw_text)
        if match:
            parser_func = globals()[pattern['parser']]
            return parser_func(match)
    
    logger.warning(f"Could not parse message: {raw_text}")
    return {'confidence': 0, 'raw_text': raw_text}
