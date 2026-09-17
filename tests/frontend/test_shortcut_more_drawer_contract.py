"""Contract: 快捷指令「更多」弹框支持点击外部与 Esc 关闭，且可在可视区内滚动。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT_INPUT = ROOT / "frontend" / "src" / "components" / "embed" / "ChatInput.vue"


def test_desktop_command_drawer_closes_on_outside_click():
    text = CHAT_INPUT.read_text(encoding="utf-8")
    assert "desktopCommandDrawerRef" in text
    assert "isDrawerExpanded.value && props.windowWidth >= 640" in text
    assert "toggleCommandDrawer" in text
    assert "if (isDrawerExpanded.value)" in text  # Esc closes first


def test_desktop_command_drawer_teleported_and_scrollable():
    text = CHAT_INPUT.read_text(encoding="utf-8")
    assert 'ref="desktopCommandDrawerRef"' in text
    assert "desktopCommandDrawerPanelRef" in text
    assert "updateDesktopCommandDrawerPosition" in text
    assert "overscroll-contain" in text
    assert "指令库 · Commands" in text
    # 打开时滚回顶部，避免只能看到底部
    assert "scrollTop = 0" in text
    assert "个人自定义" in text
    assert "系统提示词" in text
    assert "command-drawer-grid" in text
    assert "command-drawer-card" in text
    assert "calc((100% - 32px) / 5)" in text
    assert 'closest?.(\'[role="dialog"]\')' in text
