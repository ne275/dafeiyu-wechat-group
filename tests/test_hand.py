# -*- coding: utf-8 -*-
"""fish_hand 水位线与消息处理的单元测试。跑：pytest tests/ -v"""
import sys
import types
from pathlib import Path

import pytest

# mock wxauto4（Windows 专用库，测试机上不存在）
_mod = types.ModuleType("wxauto4")
_mod.WeChat = object
sys.modules.setdefault("wxauto4", _mod)
sys.path.insert(0, str(Path(__file__).parent.parent / "hand"))

import fish_hand  # noqa: E402


class M:
    def __init__(self, sender, content, attr="friend", type_="text"):
        self.sender, self.content, self.attr, self.type = sender, content, attr, type_
        self.id = str(id(self))  # 每次新建都不同，模拟 4.x 重渲染


class TestWatermark:
    def test_first_run_registers_all_as_history(self):
        msgs = [M("张三", "早上好"), M("李四", "早")]
        new, anchor = fish_hand.pick_new_messages(msgs, None)
        assert len(new) == 2  # 首轮全量返回（调用方负责跳过）
        assert anchor == fish_hand.sig_of(msgs[0]) + "␟" + fish_hand.sig_of(msgs[1])  # 消息对锚点

    def test_new_message_after_anchor(self):
        m1, m2 = M("张三", "在吗"), M("李四", "在")
        _, anchor = fish_hand.pick_new_messages([m1], None)
        new, anchor2 = fish_hand.pick_new_messages([m1, m2], anchor)
        assert [m.content for m in new] == ["在"]

    def test_duplicate_content_is_new_message(self):
        """同一句话连发两次，第二次必须被当新消息（生产事故回归：『@大肥鱼 在吗』连发）。"""
        first = [M("甲", "早"), M("张三", "@大肥鱼 在吗")]
        _, anchor = fish_hand.pick_new_messages(first, None)
        second = [M("甲", "早"), M("张三", "@大肥鱼 在吗"), M("张三", "@大肥鱼 在吗")]
        new, _ = fish_hand.pick_new_messages(second, anchor)
        assert len(new) == 1 and new[0].content == "@大肥鱼 在吗"

    def test_rerender_with_fresh_objects(self):
        """重渲染：消息对象全部更换（id 变），水位线仍按签名找到位置。"""
        old = [M("张三", "aaa"), M("李四", "bbb")]
        _, anchor = fish_hand.pick_new_messages(old, None)
        rerendered = [M("张三", "aaa"), M("李四", "bbb")]  # 新对象
        new_msg = M("王五", "ccc")
        new, _ = fish_hand.pick_new_messages(rerendered + [new_msg], anchor)
        assert [m.content for m in new] == ["ccc"]

    def test_anchor_lost_reanchors_without_processing(self):
        """视口大变导致锚点丢失：重新锚定，不把旧消息当新的。"""
        _, anchor = fish_hand.pick_new_messages([M("张三", "老消息")], None)
        fresh_scene = [M("李四", "完全不同的消息")]
        new, new_anchor = fish_hand.pick_new_messages(fresh_scene, anchor)
        assert new == [] and new_anchor is not None and new_anchor != anchor


class TestDescribe:
    def test_placeholders(self):
        assert fish_hand.describe(M("张三", "x", type_="image")) == "[对方发来一张图片]"
        assert fish_hand.describe(M("张三", "x", type_="emotion")) == "[对方发来一个表情]"
        assert fish_hand.describe(M("张三", "hello", type_="text")) == "hello"

    def test_unknown_type_returns_none(self):
        assert fish_hand.describe(M("张三", "x", type_="system")) is None
