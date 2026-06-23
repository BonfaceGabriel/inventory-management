import json
import logging

import redis
from django.conf import settings

logger = logging.getLogger(__name__)


class ConversationMemory:
    KEY_PREFIX = 'tg:conv:{chat_id}'
    MAX_EXCHANGES = 20
    TTL = 86400

    @classmethod
    def _get_client(cls):
        url = getattr(settings, 'CONVERSATION_MEMORY_REDIS_URL', 'redis://redis:6379/3')
        return redis.from_url(url)

    @classmethod
    def _key(cls, chat_id: str) -> str:
        branch = getattr(settings, 'BRANCH_NAME', 'default').replace(' ', '_')
        return f'tg:conv:{branch}:{chat_id}'

    @classmethod
    def get_history(cls, chat_id: str):
        r = cls._get_client()
        key = cls._key(chat_id)
        raw = r.lrange(key, 0, -1)
        messages = []
        for item in raw:
            try:
                messages.append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                pass
        return messages

    @classmethod
    def add_exchange(cls, chat_id: str, user_msg: str, bot_msg: str, tool_calls: list = None, chart_intent: bool = False, xlsx_intent: bool = False):
        r = cls._get_client()
        key = cls._key(chat_id)
        exchange = {
            'user': user_msg,
            'bot': bot_msg,
            'tool_calls': tool_calls or [],
            'chart_intent': chart_intent,
            'xlsx_intent': xlsx_intent,
            'timestamp': __import__('datetime').datetime.now().isoformat(),
        }
        r.rpush(key, json.dumps(exchange))
        r.ltrim(key, -cls.MAX_EXCHANGES, -1)
        r.expire(key, cls.TTL)

    @classmethod
    def has_chart_intent(cls, chat_id: str, max_exchanges: int = 1, history: list = None) -> bool:
        if history is None:
            history = cls.get_history(chat_id)
        for exchange in reversed(history[-max_exchanges:]):
            if exchange.get('chart_intent'):
                return True
        return False

    @classmethod
    def has_xlsx_intent(cls, chat_id: str, max_exchanges: int = 1, history: list = None) -> bool:
        if history is None:
            history = cls.get_history(chat_id)
        for exchange in reversed(history[-max_exchanges:]):
            if exchange.get('xlsx_intent'):
                return True
        return False

    @classmethod
    def clear(cls, chat_id: str):
        r = cls._get_client()
        key = cls._key(chat_id)
        r.delete(key)
