# -*- coding: utf-8 -*-
"""预览捷径（双模）的判定逻辑测试。"""
import re
import sys
import types
from pathlib import Path

_mod = types.ModuleType("wxauto4")
_mod.WeChat = object
sys.modules.setdefault("wxauto4", _mod)
sys.path.insert(0, str(Path(__file__).parent.parent / "hand"))
import fish_hand  # noqa: E402


def preview_path(preview):
    """与主循环一致：返回 'shortcut'（走预览）或 'window'（进窗口）。"""
    truncated = bool(re.search(r"(…|\.\.\.)\s*$", preview)) or bool(
        re.search(r"\[(图片|表情|视频|语音|文件|动画表情)\]", preview))
    has_at_fish = "大肥鱼" in preview
    return "window" if (truncated or has_at_fish) else "shortcut"


class TestPreviewShortcut:
    def test_complete_short_text(self):
        assert preview_path("张三: 哈哈") == "shortcut"

    def test_truncated_with_ellipsis(self):
        assert preview_path("张三: 这消息好长…") == "window"
        assert preview_path("张三: 这消息好长...") == "window"

    def test_media_placeholder(self):
        assert preview_path("张三: [图片]") == "window"
        assert preview_path("张三: [表情]") == "window"

    def test_at_fish_forces_window(self):
        assert preview_path("张三: @大肥鱼 在吗") == "window"

    def test_unread_count_prefix_does_not_affect(self):
        assert preview_path("[3条]张三: 哈哈") == "shortcut"
