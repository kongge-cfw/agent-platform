import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestSSOUserList:
    """测试 SSO 用户列表查询功能"""

    @pytest.mark.asyncio
    async def test_get_sso_user_list(self):
        """测试异步查询 SSO 用户列表并保持字段返回语义"""
        from app.services.sso_user import LaplacePortalApiClient

        response = MagicMock(status_code=200)
        response.json.return_value = {
            "data": [
                {
                    "displayName": "测试用户",
                    "loginName": "Test.User",
                    "userEmail": "test@example.com",
                    "userMobile": "13800000000",
                    "departmentName": "研发部",
                    "positionName": "工程师",
                    "userStatus": 0,
                    "userInfo": "tester",
                }
            ]
        }
        client = AsyncMock()
        client.post.return_value = response
        client_context = AsyncMock()
        client_context.__aenter__.return_value = client
        client_context.__aexit__.return_value = False

        with patch(
            "app.services.sso_user.httpx.AsyncClient",
            return_value=client_context,
        ) as async_client:
            users = await LaplacePortalApiClient.get_all_users()

        async_client.assert_called_once_with(verify=False, timeout=30000)
        client.post.assert_awaited_once()
        assert users == [
            {
                "code": "test.user",
                "name": "测试用户",
                "email": "test@example.com",
                "status": False,
                "mobile": "13800000000",
                "department": "研发部",
                "position": "工程师",
                "userinfo": "tester",
            }
        ]