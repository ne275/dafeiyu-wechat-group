# -*- coding: utf-8 -*-
"""鱼脑决策与整形的单元测试（不调 LLM）。跑：pytest tests/ -v"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("FISH_KEY", "test")
os.environ.setdefault("DEEPSEEK_API_KEY", "test")
os.environ["FISH_DATA_DIR"] = "/tmp/fish-test-data"

sys.path.insert(0, str(Path(__file__).parent.parent / "brain"))
import app  # noqa: E402


def reset():
    app.active_until.clear()
    app.waiting.clear()
    app.skip_streak.clear()
    app.last_active_reply.clear()
    app.daily_count.clear()


def msg(text, group="测试群", sender="张三", mention=False):
    return app.GroupMessage(group=group, sender=sender, text=text, mention=mention)


class TestDecideReply:
    def setup_method(self):
        reset()

    def test_mention_always_answers(self):
        assert app.decide_reply(msg("@大肥鱼 在吗")) == "mention"

    def test_bare_name_call(self):
        assert app.decide_reply(msg("大肥鱼")) == "mention"

    def test_quoted_fish_is_mention(self):
        assert app.decide_reply(msg("同意", mention=True)) == "mention"

    def test_placeholder_never_active(self):
        app.active_until["测试群"] = time.time() + 600
        assert app.decide_reply(msg("[对方发来一个表情]")) is None

    def test_random_wake_outside_period(self):
        # 概率 0 时周期外永远沉默
        app.ACTIVE_ENTER_PROB = 0
        assert app.decide_reply(msg("随便聊聊")) is None

    def test_active_gap_blocks_rapid_interjections(self):
        app.active_until["测试群"] = time.time() + 600
        app.last_active_reply["测试群"] = time.time()  # 刚说过
        assert app.decide_reply(msg("接着说")) is None

    def test_wait_forces_rejudge(self):
        app.active_until["测试群"] = time.time() + 600
        app.waiting["测试群"] = True
        assert app.decide_reply(msg("下半句来了")) == "active"
        assert "测试群" not in app.waiting  # 一次性消耗

    def test_daily_cap(self):
        app.daily_count[time.strftime("%F")] = 9999
        assert app.decide_reply(msg("@大肥鱼")) is None


class TestEraser:
    def test_draft_stripped(self):
        assert app.outbound_eraser("（（忍住别骂人））行吧") == "行吧"

    def test_say_shell_stripped(self):
        assert app.outbound_eraser('说"今天不值班"') == "今天不值班"

    def test_meta_blacklist_sentence_removed(self):
        out = app.outbound_eraser("这个问题很好。作为AI我没有感情。但肥鱼关心你")
        assert "作为AI" not in out and "肥鱼关心你" in out

    def test_normal_text_untouched(self):
        assert app.outbound_eraser("今天天气不错") == "今天天气不错"


class TestBubbles:
    def test_split(self):
        assert app.split_bubbles("惨\n[[next]]\n饭吃了没") == ["惨", "饭吃了没"]

    def test_single(self):
        assert app.split_bubbles("在") == ["在"]

    def test_empty_parts_dropped(self):
        assert app.split_bubbles("a[[next]]\n[[next]]b") == ["a", "b"]
