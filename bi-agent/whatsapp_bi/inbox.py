import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from .models import ConversationContext

REPLY_WINDOW_SECONDS = 24 * 60 * 60
DEDUPE_SECONDS = 8 * REPLY_WINDOW_SECONDS
CONTEXT_SECONDS = 30 * 60


@dataclass(frozen=True)
class Message:
    id: str
    sender: str
    timestamp: int
    body: str


class Inbox:
    """Store inbound messages before acknowledging their webhook."""

    def __init__(self, path: Path):
        self.path = path
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS inbox (
                    message_id TEXT PRIMARY KEY,
                    sender TEXT,
                    timestamp INTEGER NOT NULL,
                    body TEXT,
                    state TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS conversation_context (
                    sender TEXT PRIMARY KEY,
                    timestamp INTEGER NOT NULL,
                    context_json TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=0.5)

    def enqueue(self, messages: list[Message]) -> None:
        now = int(time.time())
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM inbox WHERE state != 'pending' AND timestamp < ?",
                (now - DEDUPE_SECONDS,),
            )
            connection.executemany(
                """
                INSERT INTO inbox (message_id, sender, timestamp, body)
                VALUES (?, ?, ?, ?) ON CONFLICT(message_id) DO NOTHING
                """,
                [
                    (message.id, message.sender, message.timestamp, message.body)
                    for message in messages
                    if now - REPLY_WINDOW_SECONDS < message.timestamp <= now + 300
                ],
            )

    def next_message(self) -> Message | None:
        now = int(time.time())
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "DELETE FROM conversation_context WHERE timestamp <= ?",
                (now - CONTEXT_SECONDS,),
            )
            connection.execute(
                """
                UPDATE inbox SET state = 'expired', sender = NULL, body = NULL
                WHERE state = 'pending' AND timestamp <= ?
                """,
                (now - REPLY_WINDOW_SECONDS,),
            )
            row = connection.execute(
                """
                SELECT message_id, sender, timestamp, body
                FROM inbox WHERE state = 'pending' ORDER BY rowid LIMIT 1
                """
            ).fetchone()
        return Message(*row) if row else None

    def get_context(self, message: Message) -> ConversationContext | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT context_json FROM conversation_context
                WHERE sender = ? AND timestamp <= ? AND timestamp > ?
                """,
                (message.sender, message.timestamp, int(time.time()) - CONTEXT_SECONDS),
            ).fetchone()
        return ConversationContext.model_validate_json(row[0]) if row else None

    def reserve_reply(self, message_id: str) -> bool:
        # Record the delivery attempt before calling Meta. A timeout can mean
        # Meta accepted the message, so replaying that attempt can send twice.
        with closing(self._connect()) as connection, connection:
            result = connection.execute(
                """
                UPDATE inbox SET state = 'sending', sender = NULL, body = NULL
                WHERE message_id = ? AND state = 'pending' AND timestamp > ?
                """,
                (message_id, int(time.time()) - REPLY_WINDOW_SECONDS),
            )
        return result.rowcount == 1

    def finish_reply(
        self, message: Message, *, sent: bool, context: ConversationContext | None = None
    ) -> None:
        with closing(self._connect()) as connection, connection:
            result = connection.execute(
                "UPDATE inbox SET state = ? WHERE message_id = ? AND state = 'sending'",
                ("sent" if sent else "failed", message.id),
            )
            if result.rowcount == 1 and sent and context is not None:
                connection.execute(
                    """
                    INSERT INTO conversation_context (sender, timestamp, context_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(sender) DO UPDATE SET
                        timestamp = excluded.timestamp, context_json = excluded.context_json
                    WHERE excluded.timestamp >= conversation_context.timestamp
                    """,
                    (message.sender, message.timestamp, context.model_dump_json()),
                )
