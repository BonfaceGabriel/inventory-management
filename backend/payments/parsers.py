import re
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# Regex patterns for different M-Pesa messages
# Focusing on messages received by businesses

PATTERNS = [
    {
        'name': 'buy_goods_till',
        # More flexible pattern: handles multiple spaces, mixed case names, and extra text at end
        'regex': r'(?P<tx_id>\w+)\s+Confirmed\.?\s*You have received Ksh\s*(?P<amount>[\d,]+\.\d{2})\s+from\s+(?P<sender_name>[A-Za-z\s]+?)\s+(?P<sender_phone>\d{10})\s+on\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+at\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)',
        'parser': 'parse_standard_receipt'
    },
    {
        'name': 'paybill_received',
        'regex': r'(?P<tx_id>\w+)\s+Confirmed\.?\s*You have received Ksh\s*(?P<amount>[\d,]+\.\d{2})\s+from\s+(?P<sender_name>[A-Za-z\s]+?)\s+(?P<sender_phone>\d{10})\s+on\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+at\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)\s+for account\s+(?P<account_number>\w+)',
        'parser': 'parse_paybill_receipt'
    },
    # Fallback for slight variations
    {
        'name': 'buy_goods_till_variant',
        'regex': r'(?P<tx_id>\w+)\s+Confirmed\.?\s*Ksh\s*(?P<amount>[\d,]+\.\d{2})\s+received from\s+(?P<sender_name>[A-Za-z\s]+?)\s*-?\s*(?P<sender_phone>\d{10})\s+on\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s+at\s+(?P<time>\d{1,2}:\d{2}\s*[AP]M)',
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
    # Clean up sender name: remove extra spaces and normalize
    sender_name = ' '.join(data['sender_name'].strip().split())

    return {
        'tx_id': data['tx_id'],
        'amount': normalize_amount(data['amount']),
        'sender_name': sender_name,
        'sender_phone': data['sender_phone'],
        'timestamp': normalize_timestamp(data['date'], data['time'].strip()),
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
