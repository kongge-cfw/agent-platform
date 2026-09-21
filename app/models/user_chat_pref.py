from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, String, UniqueConstraint

from app.core.orm import Base


class UserChatRuntimePref(Base):
    """对话运行时个人偏好：按嵌入应用 + 会话 owner 隔离。"""

    __tablename__ = "user_chat_runtime_prefs"
    __table_args__ = (
        UniqueConstraint(
            "embed_app_key",
            "owner_key",
            name="uk_user_chat_runtime_prefs_app_owner",
        ),
    )

    id = Column(String(36), primary_key=True)
    embed_app_key = Column(String(64), nullable=False, default="")
    owner_key = Column(String(128), nullable=False)
    override_model = Column(String(255), nullable=True)
    thinking_enable = Column(Boolean, nullable=True)
    reasoning_effort = Column(String(32), nullable=True)
    temperature = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
