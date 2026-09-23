"""bash 运行环境提醒（Bash 运行在哪）前端契约测试。

验证：
1. agentscopeSseHandlers.ts 的 dispatchAgentscopeStreamEvent 支持可选的
   onBashEnv 回调，并针对 "bash_env" 事件 type 分发。
2. EmbedChat.vue 收到环境事件后用顶部 toast 短暂提示，不再把横幅固定在输入框上方。
3. 设置面板仍可关闭该提醒，并与 localStorage 共用同一持久化键。
"""
from pathlib import Path

import pytest


pytestmark = pytest.mark.no_infrastructure
ROOT = Path(__file__).resolve().parents[2]
HANDLER = ROOT / "frontend/src/utils/agentscopeSseHandlers.ts"
BANNER = ROOT / "frontend/src/components/chat/BashEnvBanner.vue"
EMBED = ROOT / "frontend/src/views/EmbedChat.vue"
SETTINGS = ROOT / "frontend/src/components/embed/ChatSettings.vue"


def test_dispatch_accepts_optional_onbashenv_callback_and_handles_bash_env_event():
    source = HANDLER.read_text(encoding="utf-8")
    assert (
        'onBashEnv?: (env: "host" | "docker" | "e2b" | "ssh" | "k8s") => void' in source
    )
    assert "case \"bash_env\":" in source
    # 仅当值为合法的 host / docker / e2b / ssh / k8s 之一时才回调，避免脏数据触发提醒
    assert (
        'if (envVal === "docker" || envVal === "host" || envVal === "e2b" || envVal === "ssh" || envVal === "k8s")'
        in source
    )
    assert "onBashEnv(envVal)" in source


def test_embed_chat_shows_bash_env_as_toast_not_fixed_banner():
    source = EMBED.read_text(encoding="utf-8")
    assert not BANNER.exists()
    assert "BashEnvBanner" not in source
    assert "bashBannerEnv" not in source
    assert "bashBannerDismissed" not in source
    assert "handleBashEnvEvent" in source
    assert "BASH_ENV_TOAST" in source
    assert "运行在 Docker 沙箱" in source
    assert "运行在宿主机上" in source
    assert "运行在 E2B 沙箱" in source
    assert "运行在远端 SSH 主机" in source
    assert "运行在 Kubernetes 沙箱" in source
    assert 'showToast(notice.message, notice.type, 4000)' in source
    assert "if (!config.showBashBanner) return;" in source
    assert "bash_env_banner_ignored" in source
    assert source.count("dispatchAgentscopeStreamEvent") >= 3
    assert source.count("handleBashEnvEvent") >= 3


def test_bash_banner_has_settings_panel_switch():
    """设置面板提供可逆开关，可随时重新打开运行环境提醒。"""
    settings_source = SETTINGS.read_text(encoding="utf-8")
    assert "config.showBashBanner" in settings_source
    assert "handleSetBashBanner" in settings_source
    assert '<Switch :modelValue="!!config.showBashBanner"' in settings_source
    assert '@update:modelValue="handleSetBashBanner"' in settings_source
    assert "bash_env_banner_ignored" in settings_source
    assert "Bash 运行环境提醒" in settings_source


def test_bash_env_notice_no_longer_occupies_chat_input_banner_slot():
    source = EMBED.read_text(encoding="utf-8")
    assert "activeTodoTimeline" in source
    assert "<BashEnvBanner" not in source
    assert "sandboxDegradedMessage" in source
