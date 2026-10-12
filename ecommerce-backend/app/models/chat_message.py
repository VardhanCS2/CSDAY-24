from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text

from app.database.base import Base
from app.core.time import utcnow_naive


class ChatMessage(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    recipient_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, default=utcnow_naive, index=True)
