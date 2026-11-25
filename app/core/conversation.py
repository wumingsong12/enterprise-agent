import asyncio
from dataclasses import dataclass, field

@dataclass
class Session:
    turns: list[tuple[str,str]] = field(default_factory=list)
    last_order_id: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def commit(self, question, answer, verified_order_id=None):
        self.turns = (self.turns + [(question,answer)])[-3:]
        if verified_order_id:
            self.last_order_id = verified_order_id

class ConversationManager:
    def __init__(self, max_sessions=256):
        self.sessions = {}
        self.max_sessions = max_sessions

    def get(self, actor, session_id):
        key = (actor,session_id)
        if key not in self.sessions:
            if len(self.sessions) >= self.max_sessions:
                raise RuntimeError('SESSION_CAPACITY')
            self.sessions[key] = Session()
        return self.sessions[key]
