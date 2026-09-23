import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.portal.endpoints import skills
from app.core.dependencies import require_api_key

pytestmark = pytest.mark.no_infrastructure


async def _fake_user():
    return {"user_id": 1, "user_name": "tester", "role": "user"}


def _build_app(*, personal_first: bool = True, platform_admin: bool = True) -> FastAPI:
    del personal_first
    portal_router = APIRouter()
    portal_router.include_router(skills.router, prefix="/skills")

    app = FastAPI()
    app.dependency_overrides[require_api_key] = _fake_user
    if platform_admin:
        app.dependency_overrides[skills.skill_platform_admin] = _fake_user
    app.include_router(portal_router, prefix="/api/portal")
    return app


def test_platform_skill_list_is_readable_without_management_permission():
    """平台技能目录可被登录用户查询，不应绑定平台技能管理权限。"""
    with tempfile.TemporaryDirectory() as tmp:
        global_dir = Path(tmp) / "global_skills"
        global_dir.mkdir()
        skill_dir = global_dir / "public-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Public Skill\ndescription: visible to signed-in users\n---\n",
            encoding="utf-8",
        )

        with patch("app.api.portal.endpoints.skills.settings", SimpleNamespace(SKILLS_DIR=str(global_dir))):
            app = _build_app(personal_first=True, platform_admin=False)
            list_route = next(
                route
                for route in app.routes
                if getattr(route, "path", None) == "/api/portal/skills"
                and "GET" in getattr(route, "methods", set())
            )
            dependency_calls = {dependency.call for dependency in list_route.dependant.dependencies}
            assert require_api_key in dependency_calls
            assert skills.skill_platform_admin not in dependency_calls

            client = TestClient(app)
            response = client.get("/api/portal/skills")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "success"
        assert payload["data"][0]["id"] == "public-skill"


def test_personal_skill_routes_are_not_mounted():
    from app.api.portal.api import portal_router

    paths = [getattr(route, "path", "") for route in portal_router.routes]
    assert not any(str(path).startswith("/skills/personal") for path in paths)
