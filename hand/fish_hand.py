# -*- coding: utf-8 -*-
"""大肥鱼的手：wxauto 轮询群消息 -> 鱼脑 API -> 回复群里。

配置：同目录下 config.json（参照 config.example.json）
依赖：pip install wxauto4 requests
环境：Windows + 微信 PC 客户端 <= 4.1.8.107（免费版 wxauto4 上限），关闭微信自动更新
"""
import json
import time
import traceback
from collections import deque
from pathlib import Path

import requests
from wxauto4 import WeChat

# 优先读同目录 config.json；没有就用下面的内嵌默认值（方便单文件分发）
_DEFAULTS = {
    "brain_url": "https://你的域名/fish",
    "fish_key": "在此填入鱼脑密钥",
    "groups": ["你的群名（一字不差）"],
    "bot_name": "大肥鱼",
    "poll_interval": 3,
    "dry_run": False,
}
_cfg_path = Path(__file__).parent / "config.json"
_cfg = {**_DEFAULTS, **json.loads(_cfg_path.read_text(encoding="utf-8"))} if _cfg_path.exists() else _DEFAULTS
BRAIN_URL = _cfg["brain_url"].rstrip("/")
FISH_KEY = _cfg["fish_key"]
GROUPS = _cfg["groups"]
BOT_NAME = _cfg.get("bot_name", "大肥鱼")
POLL_INTERVAL = _cfg.get("poll_interval", 3)
DRY_RUN = _cfg.get("dry_run", False)  # 影子模式：思考但不对微信发送


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


EFFECT_WATCH_SEC = 60  # 鱼发言后观察群反应的时长


def report_effect(group, reply, reactions):
    """上报鱼发言后的群反应（效果追踪）。"""
    try:
        requests.post(BRAIN_URL + "/effect",
                      json={"group": group, "reply": reply, "reactions": reactions},
                      headers={"X-Fish-Key": FISH_KEY}, timeout=15)
    except Exception:
        pass


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


def send(wx, group, text, at=None, reply_to=None):
    """发送出口。优先引用原消息（reply_to），失败退回普通发送+@。dry_run 下只打印。"""
    if DRY_RUN:
        log(f"  [影子] 鱼想说: {text[:80]}")
        return
    if reply_to is not None:
        try:
            result = reply_to.quote(text)
            if result:  # WxResponse 真值 = 成功
                return
            log("  （引用失败，退回普通发送）")
        except Exception as e:
            log(f"  （引用异常，退回普通发送: {e}）")
    wx.SendMsg(text, who=group, at=at)


def fresh_message(wx, sender, content):
    """回复前重新读列表，按发送者+内容找该消息的新鲜 UI 对象。
    微信 4.x 的消息对象在滚动后会失效，鱼脑思考的几十秒里对象可能已易主，
    直接用旧对象引用会挂到别人的消息上（回复错人）。"""
    try:
        for m in reversed(wx.GetAllMessage()):
            if (m.attr == "friend" and getattr(m, "sender", None) == sender
                    and getattr(m, "content", "") == content):
                return m
    except Exception:
        pass
    return None


def main():
    mode = "影子模式（不发送）" if DRY_RUN else "正式模式"
    log(f"大肥鱼启动 | {mode} | 监听群: {GROUPS} | 每 {POLL_INTERVAL}s 轮询")
    wx = WeChat()
    # 新旧消息用「水位线」判断：记住上一条处理过的消息签名，
    # 每轮从列表末尾找它的位置，只处理它后面的。重复内容随便发，互不干扰；
    # 重渲染导致旧消息 id 变化也不影响（签名不含 id）
    last_sig = {g: None for g in GROUPS}
    first_run = {g: True for g in GROUPS}
    watch = {}  # group -> {"reply": str, "deadline": float, "reactions": list}
    last_counts = {}  # 心跳：各群读到的消息数，变化时打印
    last_preview = {}  # 会话列表哨兵：各群最新消息预览（不受聊天窗口视口卡滞影响）
    idle_cycles = {g: 0 for g in GROUPS}  # 连续未进群的轮数（用于窗口保活）
    MAINTENANCE_EVERY = 60               # 每 60 轮（~3分钟）强制保养一次窗口

    while True:
        for group in GROUPS:
            try:
                for msg in fetch_outbox(group):
                    log(f"【{group}】定时冒泡: {msg[:40]}")
                    wx.ChatWith(group)
                    send(wx, group, msg)
                    time.sleep(2)

                # 哨兵：会话列表预览变了才重进聊天（force 重进会把视口拉回最新，
                # 解决微信 4.x 实时渲染下「新消息未渲染进 UIA 树」导致的漏检）
                preview = None
                try:
                    for s in wx.GetSession():
                        if s.name == group:
                            preview = s.content
                            break
                except Exception:
                    pass
                cycle_start = time.time()
                if preview is None or preview == last_preview.get(group):
                    idle_cycles[group] += 1
                    if idle_cycles[group] < MAINTENANCE_EVERY:
                        continue  # 无新消息迹象，跳过本轮
                    # 窗口保养：长时间不动可能导致视口/渲染呆滞，定期强制重进
                    idle_cycles[group] = 0
                    wx.ChatWith(group, force=True)
                    continue
                idle_cycles[group] = 0
                last_preview[group] = preview
                wx.ChatWith(group, force=True)
                msgs = wx.GetAllMessage()
                if len(msgs) != last_counts.get(group, -1):
                    log(f"【{group}】读取到 {len(msgs)} 条消息")
                    last_counts[group] = len(msgs)
                def sig(m):
                    return f"{getattr(m, 'attr', '?')}|{getattr(m, 'sender', '?')}|{m.type}|{getattr(m, 'content', '')[:80]}"

                if first_run[group] or last_sig[group] is None:
                    log(f"【{group}】首轮登记 {len(msgs)} 条历史消息（不回复）")
                    if msgs:
                        last_sig[group] = sig(msgs[-1])
                    first_run[group] = False
                    continue

                # 从末尾找水位线位置，只处理它后面的消息
                idx = -1
                for i in range(len(msgs) - 1, -1, -1):
                    if sig(msgs[i]) == last_sig[group]:
                        idx = i
                        break
                if idx < 0:
                    log(f"【{group}】水位线丢失，重新锚定（期间消息可能漏过）")
                    last_sig[group] = sig(msgs[-1]) if msgs else last_sig[group]
                    continue
                new_msgs = msgs[idx + 1:]
                if new_msgs:
                    last_sig[group] = sig(new_msgs[-1])
                for m in new_msgs:
                    if m.attr != "friend":
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
                    # 效果追踪：鱼发言后 60s 内的群消息都记为反应
                    if group in watch and m.attr == "friend":
                        watch[group]["reactions"].append({"sender": m.sender, "text": m.content[:80]})
                    if reply:
                        log(f"  → 鱼回复({resp.get('mode')}): {reply[:50]}")
                        fresh = fresh_message(wx, m.sender, getattr(m, "content", ""))
                        if fresh is None:
                            log("  （原消息已失效，退回 @ 发送）")
                        send(wx, group, reply, at=m.sender, reply_to=fresh)
                        if not DRY_RUN:
                            watch[group] = {"reply": reply, "deadline": time.time() + EFFECT_WATCH_SEC,
                                            "reactions": []}
                        time.sleep(2)
                    else:
                        log("  → 鱼选择沉默")
                first_run[group] = False
                # 上报到期了的效果观察
                if group in watch and time.time() > watch[group]["deadline"]:
                    w = watch.pop(group)
                    n = len(w["reactions"])
                    log(f"【{group}】效果追踪：鱼说「{w['reply'][:30]}」后 60s 内有 {n} 条反应")
                    report_effect(group, w["reply"], w["reactions"])
            except Exception:
                log(f"【{group}】轮询出错:")
                traceback.print_exc()
            elapsed = time.time() - cycle_start
            if elapsed > 20:
                log(f"⚠️ 本轮耗时 {elapsed:.0f}s（正常<5s）——窗口可能呆滞。"
                    "若持续出现：检查微信窗口是否被最小化、挂机宝是否锁屏；"
                    "Ctrl+C 无响应时用任务管理器结束 python.exe")
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
