import logging
import json
from app.services.ai.tools.tool_compat import tool
from app.services.ai.memory_service import ltm_service

logger = logging.getLogger(__name__)


def _ltm_user_id(requested: str | None = None) -> str | None:
    """长期记忆必须跟会话 owner 隔离；忽略模型传入的他人/签发人 ID。"""
    from app.core.context import get_current_agent_context
    from app.services.ai.conversation_identity import try_session_user_id_from_agent_context

    uid = try_session_user_id_from_agent_context(get_current_agent_context())
    if uid:
        return uid
    requested = str(requested or "").strip()
    return requested or None

@tool
async def update_user_preference(user_id: str, key: str, value: str) -> str:
    """
    持久化地将用户的个性偏好、行为习惯或关于用户的核心事实，以 Key-Value 键值对的形式异步写入 Redis 长期记忆哈希（Hash）中。
    
    Args:
        user_id: 用户的 ID 标识。
        key: 长期偏好或事实的键名 (如 theme, language, user_role, custom_fact)。
        value: 对应的具体偏好内容值 (如 dark, Chinese, senior_data_analyst)。
    """
    try:
        uid = _ltm_user_id(user_id)
        if not uid:
            return "无法识别当前用户，拒绝写入长期记忆。"
        success = await ltm_service.update_preference(uid, key, value)
        if success:
            return f"成功持久化保存用户偏好记忆！已记录 '{key}': '{value}'。"
        else:
            return "提示：保存记忆失败，可能是 Redis 服务不可用。"
    except Exception as e:
        return f"持久化记忆操作异常: {str(e)}"

@tool
async def fetch_user_long_term_memory(user_id: str) -> str:
    """
    主动查询并拉取当前用户在 Redis 长期记忆哈希（Hash）中存储的所有历史核心事实和偏好记录。
    
    Args:
        user_id: 用户的 ID 标识。
    """
    try:
        uid = _ltm_user_id(user_id)
        if not uid:
            return "无法识别当前用户，拒绝检索长期记忆。"
        data = await ltm_service.fetch_memory(uid)
        if not data:
            return "当前用户没有任何长期记忆或事实偏好记录。"
            
        return f"查询到用户的长期记忆：\n```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
    except Exception as e:
        return f"检索长期记忆操作异常: {str(e)}"

@tool
async def delete_user_preference(user_id: str, key: str) -> str:
    """
    持久化地将用户在 Redis 长期记忆哈希（Hash）中存储的某个特定偏好、行为习惯或关于用户的核心事实进行清除。
    
    Args:
        user_id: 用户的 ID 标识。
        key: 需要清除的长期偏好或事实的键名。
    """
    try:
        uid = _ltm_user_id(user_id)
        if not uid:
            return "无法识别当前用户，拒绝清除长期记忆。"
        success = await ltm_service.delete_preference(uid, key)
        if success:
            return f"成功删除用户偏好记忆！已清除键为 '{key}' 的偏好记录。"
        else:
            return "提示：删除记忆失败，可能是 Redis 服务不可用。"
    except Exception as e:
        return f"清除长期记忆操作异常: {str(e)}"
