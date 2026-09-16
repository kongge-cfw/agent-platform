from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.core.orm import Base


class SysUiCard(Base):
    __tablename__ = "sys_ui_cards"

    id = Column(String(36), primary_key=True)
    card_key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    render_type = Column(String(16), nullable=False, default="iframe")
    url = Column(String(1024), nullable=False)
    allowed_origins = Column(Text, nullable=False, default="[]")
    allowed_actions = Column(Text, nullable=False, default="[]")
    allowed_agent_ids = Column(Text, nullable=False, default="[]")
    default_height = Column(Integer, nullable=False, default=480)
    token_ttl_seconds = Column(Integer, nullable=False, default=600)
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
