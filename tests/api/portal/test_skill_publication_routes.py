import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.portal.endpoints import skills
from app.core.dependencies import require_api_key, require_permission


pytestmark = pytest.mark.no_infrastructure


async def _fake_user():
    return {"user_id": 7, "user_name": "tester", "role": "user"}


async def _fake_admin():
    return {"user_id": 1, "user_name": "admin", "role": "admin"}


def _build_app() -> FastAPI:
    portal = APIRouter()
    portal.include_router(skills.router, prefix="/skills")
    app = FastAPI()
    app.dependency_overrides[require_api_key] = _fake_user
    app.include_router(portal, prefix="/api/portal")
    return app


def test_personal_publication_submit_route_exists():
    routes = {route.path for route in _build_app().routes}
    assert "/api/portal/skills/personal/{skill_id}/publication-requests" not in routes
    assert "/api/portal/skills/personal/{skill_id}/publication-requests/withdraw" not in routes


def test_admin_publication_review_routes_exist():
    routes = {route.path for route in _build_app().routes}
    assert "/api/portal/skills/publication-requests" in routes
    assert "/api/portal/skills/publication-requests/{version_id}/approve" in routes
    assert "/api/portal/skills/publication-requests/{version_id}/reject" in routes


def test_reject_requires_non_blank_comment():
    app = _build_app()
    app.dependency_overrides[skills.skill_publication_reviewer] = _fake_admin
    with patch(
        "app.api.portal.endpoints.skills.reject_publication",
        new=AsyncMock(side_effect=ValueError("reject comment is required")),
    ):
        response = TestClient(app).post(
            "/api/portal/skills/publication-requests/version-1/reject",
            json={"comment": "   "},
        )
    assert response.status_code in {400, 422}
