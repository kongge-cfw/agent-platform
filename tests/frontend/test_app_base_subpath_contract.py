from pathlib import Path

import pytest


pytestmark = pytest.mark.no_infrastructure

ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_internal_auth_and_audit_use_stripped_request_path():
    guard = _read("app/services/embed_api_guard.py")
    middleware = _read("app/core/middleware.py")
    v1_access = _read("app/core/v1_api_access.py")
    dependencies = _read("app/core/dependencies.py")
    prefix = _read("app/core/app_prefix.py")

    assert "def internal_request_path(" in prefix
    assert "def strip_root_from_path(" in prefix
    assert "def inferred_root_path(" in prefix
    assert "internal_request_path(request)" in guard
    assert "path = request.url.path" not in guard
    assert "internal_request_path(request).startswith(\"/api/\")" in middleware
    assert "endpoint=internal_request_path(request)" in middleware
    assert "url_path = internal_request_path(request)" in v1_access
    assert "is_v1_api_whitelisted(internal_request_path(request))" in dependencies


def test_public_mcp_echo_and_scheduler_urls_apply_root_path():
    platform = _read("app/services/mcp/platform_mcp.py")
    oauth = _read("app/api/mcp_platform.py")
    desk = _read("app/api/portal/endpoints/mcp_service.py")
    echo = _read("app/services/mcp/echo_server.py")
    scheduler = _read("app/services/ai/scheduler_service.py")

    assert "return public_base_url()" in platform
    assert "return public_base_url()" in oauth
    assert "base = public_base_url()" in desk
    assert "apply_root_to_public_base(parsed[0])" in echo
    assert "apply_root_to_public_base(str(settings.APP_PUBLIC_URL" in scheduler


def test_frontend_native_navigation_and_storage_are_prefixed():
    app_base = _read("frontend/src/utils/appBase.ts")
    chat = _read("frontend/src/views/Chat.vue")
    agents = _read("frontend/src/views/AgentManagement.vue")
    widget = _read("frontend/src/views/WidgetDebugger.vue")
    index = _read("frontend/index.html")
    skills = _read("frontend/src/components/embed/SkillCascadeMenu.vue")
    mcp_menu = _read("frontend/src/components/embed/McpCascadeMenu.vue")

    assert "authStorageKey" in app_base
    assert "clearClientAuth" in app_base
    assert "Storage.prototype.clear" in app_base
    assert "installEventSourcePrefix" in app_base
    assert "class PatchedEventSource extends OriginalEventSource" in app_base
    assert "iframeUrl.value = withAppBase('/embed/chat')" in chat
    assert "window.open(withAppBase(url), \"_blank\")" in agents
    assert "getAppBasePath()" in widget
    assert "withAppBase('/embed/chat?strict_token=1')" in widget
    assert 'href="./favicon.svg"' in index
    assert "withAppBase('/dashboard/personal?tab=skills')" in skills
    assert "withAppBase('/dashboard/personal?tab=mcp')" in mcp_menu
    assert "isPlatformRoutedUrl" in _read("frontend/src/utils/workspaceFilePreview.ts")
    assert "stripAppBase(file.url)" in _read("frontend/src/utils/attachmentImages.ts")
    assert "isPlatformRoutedUrl(raw)" in _read("frontend/src/utils/messageBrowserLinks.ts")


def test_nginx_and_ingress_subdirectory_examples_are_complete():
    nginx = _read("docker/nginx-zhiyuan.example.conf")
    ingress = _read("k8s_deploy/ingress-zhiyuan.example.yaml")
    configmap = _read("k8s_deploy/configmap.yaml")
    cookie = _read("app/core/app_prefix.py")
    browser = _read("app/api/v1/endpoints/browser.py")
    openapi = _read("app/core/openapi.py")
    files = _read("app/services/ai/tools/generated_file_service.py")
    frontend = _read("frontend/src/utils/appBase.ts")

    assert 'proxy_set_header Connection "upgrade"' not in nginx
    assert "X-Forwarded-Host $host" in nginx
    assert "set $nanzi_connection_upgrade" in nginx
    assert "proxy_read_timeout 3600s" in nginx
    assert "gzip off" in nginx
    assert "进程必须设置 APP_ROOT_PATH=/zhiyuan" in nginx
    assert "path: /zhiyuan(/|$)(.*)" in ingress
    assert "ConfigMap APP_ROOT_PATH=/zhiyuan" in ingress
    assert "session-cookie-path: \"/zhiyuan\"" in ingress
    assert 'APP_ROOT_PATH: ""' in configmap
    overlay = _read("k8s_zhiyuan/kustomization.yaml")
    overlay_patch = _read("k8s_zhiyuan/configmap-root-path.yaml")
    overlay_ingress = _read("k8s_zhiyuan/ingress.yaml")
    assert "../k8s_deploy" in overlay
    assert "- ingress.yaml" in overlay
    assert 'APP_ROOT_PATH: "/zhiyuan"' in overlay_patch
    assert "path: /zhiyuan(/|$)(.*)" in overlay_ingress
    assert "session-cookie-path: \"/zhiyuan\"" in overlay_ingress
    install = _read("k8s_deploy/install.sh")
    assert 'APP_ROOT_PATH: "${CFG_ROOT_PATH}"' in install
    assert "ingress-zhiyuan.example.yaml" in install
    assert "apply_root_if_platform_origin" in files
    assert "clearClientAuth" in _read("frontend/src/main.ts")
    assert "clearClientAuth" in _read("frontend/src/utils/axios.ts")
    assert "secure=request_is_secure(request) if secure is None else secure" in cookie
    assert "secure=request_is_secure(request)" in browser
    assert '_path_already_has_root' in cookie
    assert 'openapi_schema["servers"]' in openapi
    assert "configured_base:" in files or "if configured_base:" in files
    assert "isPlatformRoutedUrl" in frontend
    assert "bind_platform_mcp_public_urls" in _read("app/services/mcp/platform_mcp.py")
    assert "strip_root_from_path(" in cookie
    assert 'RedirectResponse(url=f"{root}/"' in cookie
    assert 'scope["root_path"] = root' not in cookie
    assert "_request_prefix.set(root)" in cookie
