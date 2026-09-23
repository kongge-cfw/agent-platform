from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Column, DateTime, String, Text

from app.core.orm import Base


class SysEmbedApp(Base):
    """宿主系统注册的嵌入应用：控制面策略，不代替业务 IAM。"""

    __tablename__ = "sys_embed_apps"

    id = Column(String(36), primary_key=True)
    app_key = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    description = Column(Text, nullable=True)
    role_id = Column(BigInteger, nullable=True)
    lock_entry_agent = Column(Boolean, nullable=False, default=False)
    default_entry_agent_id = Column(String(64), nullable=True)
    allowed_origins = Column(Text, nullable=False, default="[]")
    require_identity = Column(Boolean, nullable=False, default=True)
    claim_keys = Column(Text, nullable=False, default="[]")
    data_permission_mode = Column(String(32), nullable=False, default="nanzi_sql_rewrite")
    shortcut_prompts = Column(Text, nullable=False, default="[]")
    chat_settings = Column(Text, nullable=False, default="{}")
    is_active = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(64), nullable=True)
    updated_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
