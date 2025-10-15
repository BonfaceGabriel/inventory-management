
from celery import shared_task
from django.db import transaction
from .models import RawMessage, Transaction
from .parsers import parse_mpesa_sms
from .serializers import TransactionSerializer
import logging
import hashlib
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger(__name__)

@shared_task
def process_raw_message(message_id):
    try:
        message = RawMessage.objects.get(id=message_id)
        if message.processed:
            logger.info(f"Message {message_id} has already been processed.")
            return

        parsed_data = parse_mpesa_sms(message.raw_text)
        
        if parsed_data and parsed_data.get('confidence', 0) > 0.8:
            tx_id = parsed_data['tx_id']
            amount = parsed_data['amount']
            timestamp = parsed_data['timestamp']

            # Compute unique_hash
            hash_string = f"{tx_id}|{amount}|{timestamp}"
            unique_hash = hashlib.sha256(hash_string.encode()).hexdigest()

            try:
                with transaction.atomic():
                    # Create a Transaction record
                    new_transaction = Transaction.objects.create(
                        tx_id=tx_id,
                        amount=amount,
                        sender_name=parsed_data.get('sender_name', ''),
                        sender_phone=parsed_data.get('sender_phone', ''),
                        timestamp=timestamp,
                        gateway_type=parsed_data['gateway_type'],
                        destination_number=parsed_data.get('destination_number', ''),
                        confidence=parsed_data['confidence'],
                        unique_hash=unique_hash,
                        amount_expected=amount
                    )
                    message.transaction = new_transaction
                    message.processed = True
                    message.save()
                    logger.info(f"Successfully processed message {message_id} and created transaction.")

                    # Broadcast new transaction to WebSocket clients
                    _broadcast_transaction_created(new_transaction)

            except Exception as e:
                logger.warning(f"Could not create transaction for message {message_id}. It might be a duplicate. Error: {e}")
                # Find the existing transaction and link the raw message to it
                existing_transaction = Transaction.objects.get(unique_hash=unique_hash)
                message.transaction = existing_transaction
                message.processed = True
                message.save()

        else:
            logger.warning(f"Failed to parse message {message_id} with sufficient confidence.")

    except RawMessage.DoesNotExist:
        logger.error(f"RawMessage with id {message_id} does not exist.")
    except Exception as e:
        logger.error(f"An error occurred while processing message {message_id}: {e}")


def _broadcast_transaction_created(transaction):
    """
    Broadcast a newly created transaction to WebSocket clients.

    Args:
        transaction: Transaction instance
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            serializer = TransactionSerializer(transaction)
            async_to_sync(channel_layer.group_send)(
                'transactions',
                {
                    'type': 'transaction.created',
                    'transaction': serializer.data
                }
            )
            logger.info(f"Broadcasted transaction {transaction.tx_id} to WebSocket clients")
    except Exception as e:
        logger.error(f"Failed to broadcast transaction {transaction.tx_id}: {e}")
