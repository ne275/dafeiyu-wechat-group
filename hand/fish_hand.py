# -*- coding: utf-8 -*-
"""大肥鱼的手：wxauto 轮询群消息 -> 鱼脑 API -> 回复群里。

配置：同目录下 config.json（参照 config.example.json）
依赖：pip install wxauto4 requests
环境：Windows + 微信 PC 客户端 <= 4.1.8.107（免费版 wxauto4 上限），关闭微信自动更新
"""
import json
import time
import traceback
from pathlib import Path

import requests
from wxauto4 import WeChat

_cfg = json.loads((Path(__file__).parent / "config.json").read_text(encoding="utf-8"))
BRAIN_URL = _cfg["brain_url"].rstrip("/")
FISH_KEY = _cfg["fish_key"]
GROUPS = _cfg["groups"]
BOT_NAME = _cfg.get("bot_name", "大肥鱼")
POLL_INTERVAL = _cfg.get("poll_interval", 3)


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


def brain_post(path, payload):
    try:
        r = requests.post(BRAIN_URL + path, json=payload,
                          headers={"X-Fish-Key": FISH_KEY}, timeout=70)
        if r.status_code == 200:
            return r.json()
        log(f"⚠️ 鱼脑 HTTP {r.status_code}: {r.text[:120]}")
    except Exception as e:
        log(f"⚠️ 鱼脑连接失败: {e}")
    return {}


def fetch_outbox(group):
    try:
        r = requests.get(BRAIN_URL + "/outbox", params={"group": group},
                         headers={"X-Fish-Key": FISH_KEY}, timeout=15)
        if r.status_code == 200:
            return r.json().get("messages", [])
    except Exception:
        pass
    return []


def describe(m):
    """把非文本消息翻译成鱼能懂的占位文本。"""
    if m.type == "text":
        return m.content
    if m.type == "quote":
        return m.content
    if m.type == "image":
        return "[对方发来一张图片]"
    if m.type == "emotion":
        return "[对方发来一个表情]"
    if m.type == "voice":
        return "[对方发来一条语音]"
    if m.type == "video":
        return "[对方发来一个视频]"
    if m.type == "link":
        return f"[对方发来一个链接] {getattr(m, 'content', '')}"
    return None


def main():
    log(f"大肥鱼启动 | 监听群: {GROUPS} | 每 {POLL_INTERVAL}s 轮询")
    wx = WeChat()
    seen = {g: set() for g in GROUPS}
    first_run = {g: True for g in GROUPS}

    while True:
        for group in GROUPS:
            try:
                for msg in fetch_outbox(group):
                    log(f"【{group}】定时冒泡: {msg[:40]}")
                    wx.ChatWith(group)
                    wx.SendMsg(msg, who=group)
                    time.sleep(2)

                wx.ChatWith(group)
                msgs = wx.GetAllMessage()
                if first_run[group]:
                    log(f"【{group}】首轮登记 {len(msgs)} 条历史消息（不回复）")
                for m in msgs:
                    key = getattr(m, "hash", None) or m.id
                    if key in seen[group]:
                        continue
                    seen[group].add(key)
                    if first_run[group] or m.attr != "friend":
                        continue
                    text = describe(m)
                    if not text:
                        continue
                    mention = False
                    if m.type == "quote":
                        qnick = getattr(m, "quote_nickname", "") or ""
                        qcontent = getattr(m, "quote_content", "") or ""
                        if BOT_NAME in qnick:
                            mention = True
                            text = f"{m.content}（{m.sender} 引用了你之前的话：「{qcontent[:60]}」）"
                    log(f"【{group}】{m.sender}: {text[:60]}")
                    resp = brain_post("/group-message", {
                        "group": group, "sender": m.sender,
                        "text": text, "mention": mention,
                    })
                    reply = resp.get("reply")
                    if reply:
                        log(f"  → 鱼回复({resp.get('mode')}): {reply[:50]}")
                        wx.SendMsg(reply, who=group, at=m.sender)
                        time.sleep(2)
                    else:
                        log("  → 鱼选择沉默")
                first_run[group] = False
            except Exception:
                log(f"【{group}】轮询出错:")
                traceback.print_exc()
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
