import json
from unittest.mock import patch, MagicMock
from django.test import TestCase

from payments.services.bi_conversation_service import ConversationMemory


class TestConversationMemory(TestCase):

    def setUp(self):
        self.mock_redis = MagicMock()
        self.redis_patcher = patch('payments.services.bi_conversation_service.redis.from_url')
        self.mock_from_url = self.redis_patcher.start()
        self.mock_from_url.return_value = self.mock_redis

    def tearDown(self):
        self.redis_patcher.stop()

    def test_get_history_empty(self):
        self.mock_redis.lrange.return_value = []
        history = ConversationMemory.get_history('chat_123')
        self.assertEqual(history, [])
        self.mock_redis.lrange.assert_called_once()

    def test_get_history_returns_parsed_json(self):
        self.mock_redis.lrange.return_value = [
            json.dumps({'user': 'hi', 'bot': 'hello'}).encode(),
        ]
        history = ConversationMemory.get_history('chat_123')
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['user'], 'hi')
        self.assertEqual(history[0]['bot'], 'hello')

    def test_get_history_skips_invalid_json(self):
        self.mock_redis.lrange.return_value = [
            b'not-json',
            json.dumps({'user': 'hi', 'bot': 'hello'}).encode(),
        ]
        history = ConversationMemory.get_history('chat_123')
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['user'], 'hi')

    def test_add_exchange_stores_and_trims(self):
        self.mock_redis.rpush.return_value = 1
        ConversationMemory.add_exchange('chat_123', 'how did we do?', 'Great day!')
        self.mock_redis.rpush.assert_called_once()
        self.mock_redis.ltrim.assert_called_once()
        self.mock_redis.expire.assert_called_once()
        call_arg = self.mock_redis.rpush.call_args[0][1]
        exchange = json.loads(call_arg)
        self.assertEqual(exchange['user'], 'how did we do?')
        self.assertEqual(exchange['bot'], 'Great day!')
        self.assertEqual(exchange['tool_calls'], [])

    def test_add_exchange_with_tool_calls(self):
        ConversationMemory.add_exchange('chat_123', 'revenue?', 'Revenue data', [{'fn': 'get_revenue'}])
        call_arg = self.mock_redis.rpush.call_args[0][1]
        exchange = json.loads(call_arg)
        self.assertEqual(exchange['tool_calls'], [{'fn': 'get_revenue'}])

    def test_clear_memory(self):
        ConversationMemory.clear('chat_123')
        self.mock_redis.delete.assert_called_once()

    def test_multiple_users_isolation(self):
        self.mock_redis.lrange.return_value = [
            json.dumps({'user': 'msg1', 'bot': 'resp1'}).encode(),
        ]
        h1 = ConversationMemory.get_history('user_a')

        self.mock_redis.lrange.return_value = [
            json.dumps({'user': 'msg2', 'bot': 'resp2'}).encode(),
        ]
        h2 = ConversationMemory.get_history('user_b')

        self.assertEqual(h1[0]['user'], 'msg1')
        self.assertEqual(h2[0]['user'], 'msg2')
        self.assertNotEqual(h1, h2)

    def test_max_exchanges_trims_old(self):
        # MAX_EXCHANGES is 20 — verify ltrim is called with -20
        ConversationMemory.add_exchange('chat_123', 'q', 'a')
        args, kwargs = self.mock_redis.ltrim.call_args
        self.assertEqual(args[1], -ConversationMemory.MAX_EXCHANGES)
