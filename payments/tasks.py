
from celery import shared_task
from .models import RawMessage
from .parsers import parse_mpesa_sms
import logging

logger = logging.getLogger(__name__)

@shared_task
def process_raw_message(message_id):
    try:
        message = RawMessage.objects.get(id=message_id)
        parsed_data = parse_mpesa_sms(message.raw_text)
        if parsed_data:
            # Here you would typically save the parsed data to a new model
            # For now, we'll just log it and mark the message as processed
            logger.info(f"Successfully parsed message {message_id}: {parsed_data}")
            message.processed = True
            message.save()
        else:
            logger.warning(f"Failed to parse message {message_id}")
    except RawMessage.DoesNotExist:
        logger.error(f"RawMessage with id {message_id} does not exist.")
    except Exception as e:
        logger.error(f"An error occurred while processing message {message_id}: {e}")
