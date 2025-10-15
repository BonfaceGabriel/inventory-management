"""
WebSocket consumers for real-time transaction updates.

Handles WebSocket connections and broadcasts new transactions to connected clients.
"""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Transaction
from .serializers import TransactionSerializer


class TransactionConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time transaction updates.

    Clients connect to ws://host/ws/transactions/ to receive:
    - New transaction notifications
    - Transaction status updates
    - Payment updates

    Messages sent to clients:
    {
        "type": "transaction.created" | "transaction.updated",
        "transaction": {...serialized transaction data...}
    }
    """

    async def connect(self):
        """
        Called when WebSocket connection is established.
        Add this connection to the 'transactions' group.
        """
        try:
            self.group_name = 'transactions'

            # Join transactions group
            if self.channel_layer:
                await self.channel_layer.group_add(
                    self.group_name,
                    self.channel_name
                )
            else:
                print("WARNING: Channel layer is None, WebSocket will work but no group messaging")

            await self.accept()
        except Exception as e:
            print(f"ERROR in connect: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            await self.close()

    async def disconnect(self, close_code):
        """
        Called when WebSocket connection is closed.
        Remove this connection from the 'transactions' group.
        """
        # Leave transactions group
        if self.channel_layer and hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """
        Called when we receive a message from the WebSocket.
        Currently not used - this is primarily a broadcast-only channel.

        Could be extended to support:
        - Subscription filtering (e.g., only certain gateways)
        - Transaction status queries
        """
        pass

    async def transaction_created(self, event):
        """
        Handler for 'transaction.created' events sent to the group.
        Forwards the transaction data to the WebSocket client.
        """
        # Send transaction data to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'transaction.created',
            'transaction': event['transaction']
        }))

    async def transaction_updated(self, event):
        """
        Handler for 'transaction.updated' events sent to the group.
        Forwards the updated transaction data to the WebSocket client.
        """
        # Send updated transaction data to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'transaction.updated',
            'transaction': event['transaction']
        }))


# Utility functions for broadcasting from sync code

async def broadcast_transaction_created(transaction_data):
    """
    Broadcast a newly created transaction to all connected WebSocket clients.

    Args:
        transaction_data (dict): Serialized transaction data
    """
    from channels.layers import get_channel_layer
    channel_layer = get_channel_layer()

    await channel_layer.group_send(
        'transactions',
        {
            'type': 'transaction.created',
            'transaction': transaction_data
        }
    )


async def broadcast_transaction_updated(transaction_data):
    """
    Broadcast a transaction update to all connected WebSocket clients.

    Args:
        transaction_data (dict): Serialized transaction data
    """
    from channels.layers import get_channel_layer
    channel_layer = get_channel_layer()

    await channel_layer.group_send(
        'transactions',
        {
            'type': 'transaction.updated',
            'transaction': transaction_data
        }
    )


@database_sync_to_async
def get_transaction_data(transaction):
    """
    Get serialized transaction data (async wrapper for sync serializer).

    Args:
        transaction (Transaction): Transaction instance

    Returns:
        dict: Serialized transaction data
    """
    serializer = TransactionSerializer(transaction)
    return serializer.data
