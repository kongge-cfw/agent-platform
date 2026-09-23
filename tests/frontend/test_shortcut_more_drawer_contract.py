"""Contract: 快捷指令「更多」打开右侧抽屉，一行一条，可添加指令。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT_INPUT = ROOT / "frontend" / "src" / "components" / "embed" / "ChatInput.vue"


def test_shortcut_more_opens_side_drawer():
    text = CHAT_INPUT.read_text(encoding="utf-8")
    assert 'data-shortcut-more' in text
    assert "toggleCommandDrawer" in text
    assert 'v-if="isDrawerExpanded"' in text
    assert "absolute inset-y-0 right-0" in text
    assert "command-drawer-row" in text
    assert "commandDrawerSections" in text
    assert "if (isDrawerExpanded.value)" in text
    assert "overscroll-contain" in text
    assert "commandDrawerListRef" in text
    assert "scrollTop = 0" in text
    assert "指令库" in text
    assert ">更多<" not in text
    drawer = text.split("快捷指令抽屉", 1)[1].split("新会话类型菜单", 1)[0]
    assert "shortcutCommandPreview" not in drawer
    assert 'title="编辑这条指令"' in drawer
    assert 'title="删除这条指令"' in drawer
    assert "canEditDrawerCommand" in drawer
    assert "section.manageable && canDeleteCommand" not in drawer
    assert "command-drawer-grid" not in text
    assert "desktopCommandDrawerRef" not in text


def test_shortcut_drawer_supports_add_without_plus_button():
    text = CHAT_INPUT.read_text(encoding="utf-8")
    assert "添加指令" in text
    assert "openAddCommandFromDrawer" in text
    assert 'emit("open-command-manager")' in text
    assert 'title="新建快捷指令"' not in text
