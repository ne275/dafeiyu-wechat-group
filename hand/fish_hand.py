# -*- coding: utf-8 -*-
"""大肥鱼的手：wxauto 轮询群消息 -> 鱼脑 API -> 回复群里。

配置：同目录下 config.json（参照 config.example.json）
依赖：pip install wxauto4 requests
环境：Windows + 微信 PC 客户端 <= 4.1.8.107（免费版 wxauto4 上限），关闭微信自动更新
"""
import json
import re
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
HAND_VERSION = "4.4"  # 每次行为修改必须递增——日志里用来确认改动是否生效

_cfg_path = Path(__file__).parent / "config.json"
_cfg = {**_DEFAULTS, **json.loads(_cfg_path.read_text(encoding="utf-8"))} if _cfg_path.exists() else _DEFAULTS
BRAIN_URL = _cfg["brain_url"].rstrip("/")
FISH_KEY = _cfg["fish_key"]
GROUPS = _cfg["groups"]
BOT_NAME = _cfg.get("bot_name", "大肥鱼")
POLL_INTERVAL = _cfg.get("poll_interval", 1)
DRY_RUN = _cfg.get("dry_run", False)  # 影子模式：思考但不对微信发送
SEND_GAP = _cfg.get("send_gap", 0.3)  # 多气泡连发的技术间隔（防输入框竞争，非表演延迟）

# 尽量拉大聊天窗口（挂机宝虚拟显示器可能限制实际高度，设了不坏）
try:
    from wxauto4.param import WxParam
    WxParam.CHAT_WINDOW_SIZE = (1200, 4800)
except Exception:
    pass


_LOG_FILE = Path(__file__).parent / "fish_hand.log"


def log(*a):
    line = " ".join(str(x) for x in a)
    line = f"{time.strftime('[%m-%d %H:%M:%S]')} {line}"
    print(line, flush=True)
    try:
        # 超过 2MB 轮转为 .old，避免无限增长
        if _LOG_FILE.exists() and _LOG_FILE.stat().st_size > 2 * 1024 * 1024:
            _LOG_FILE.replace(_LOG_FILE.with_suffix(".log.old"))
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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


def sig_of(m):
    """消息签名：属性|发送者|类型|内容前80字。不含 UI id（重渲染后会变）。"""
    return f"{getattr(m, 'attr', '?')}|{getattr(m, 'sender', '?')}|{m.type}|{getattr(m, 'content', '')[:80]}"


def pick_new_messages(msgs, last_sig):
    """水位线纯函数：返回（新消息列表, 新水位线）。
    水位线 = 末尾两条消息的签名对（防『新消息与锚点同内容』的歧义）。
    首轮（last_sig=None）返回全量当历史处理。锚点丢失时重新锚定并返回空。"""
    if not msgs:
        return [], last_sig

    def pair_at(i):  # 以 msgs[i] 结尾的消息对签名
        prev = sig_of(msgs[i - 1]) if i > 0 else "<头>"
        return prev + "␟" + sig_of(msgs[i])

    if last_sig is None:
        return list(msgs), pair_at(len(msgs) - 1)
    idx = -1
    for i in range(len(msgs) - 1, -1, -1):
        if pair_at(i) == last_sig:
            idx = i
            break
    if idx < 0:
        return [], pair_at(len(msgs) - 1)  # 水位线丢失：重新锚定
    return list(msgs[idx + 1:]), pair_at(len(msgs) - 1)


class PhaseTimer:
    """分阶段计时：找出 UIA 卡顿的具体环节。"""
    def __init__(self, group):
        self.group, self.t, self.phases = group, time.time(), []

    def mark(self, name):
        now = time.time()
        self.phases.append((name, now - self.t))
        self.t = now

    def report_slow(self):
        for name, dur in self.phases:
            if dur > 5:
                log(f"⚠️【{self.group}】慢环节: {name} 耗时 {dur:.0f}s")


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
    wx.SendMsg(text, at=at)  # 不传 who：当前就在群里，省一次窗口切换


def main():
    mode = "影子模式（不发送）" if DRY_RUN else "正式模式"
    log(f"大肥鱼启动 v{HAND_VERSION} | {mode} | 监听群: {GROUPS} | 每 {POLL_INTERVAL}s 轮询")
    heartbeat = Path(__file__).parent / "fish_heartbeat"  # 看门狗用：每轮刷新
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
            cycle_start = time.time()
            pt = PhaseTimer(group)
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
                pt.mark("GetSession")
                if preview is None or preview == last_preview.get(group):
                    idle_cycles[group] += 1
                    if idle_cycles[group] < MAINTENANCE_EVERY:
                        continue  # 无新消息迹象，跳过本轮
                    # 窗口保养：长时间不动可能导致视口/渲染呆滞，定期强制重进
                    idle_cycles[group] = 0
                    wx.ChatWith(group, force=True)
                    continue
                # 预览变了才动窗口。force=True 会触发全量重渲染（~9s），
                # 只在「检测停滞」的保养轮里用；平时轻量切换即可
                idle_cycles[group] = 0
                last_preview[group] = preview
                wx.ChatWith(group)
                pt.mark("ChatWith")
                msgs = wx.GetAllMessage()
                pt.mark("GetAllMessage")
                if len(msgs) != last_counts.get(group, -1):
                    log(f"【{group}】读取到 {len(msgs)} 条消息")
                    last_counts[group] = len(msgs)
                if first_run[group]:
                    log(f"【{group}】首轮登记 {len(msgs)} 条历史消息（不回复）")
                    if msgs:
                        last_sig[group] = sig_of(msgs[-1])
                    first_run[group] = False
                    continue

                # 水位线：只处理上一条已处理消息之后的新消息（纯函数，见 pick_new_messages）
                prev_anchor = last_sig[group]
                new_msgs, new_anchor = pick_new_messages(msgs, prev_anchor)
                if prev_anchor is not None and not new_msgs and new_anchor != prev_anchor:
                    log(f"【{group}】水位线丢失，用会话预览兜底（内容可能截断）")
                    # 兜底：预览形如「[3条]张三: 内容」或「张三: 内容」，当作一条新消息处理
                    m2 = re.match(r"^(?:\[\d+条\])?([^:：]+)[:：]\s*(.+)$", preview or "")
                    if m2:
                        pseudo = type("PseudoMsg", (), {"sender": m2.group(1).strip(),
                                                        "content": m2.group(2).strip(),
                                                        "attr": "friend", "type": "text"})()
                        new_msgs = [pseudo]
                last_sig[group] = new_anchor
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
                    pt.mark("问鱼脑")
                    reply = resp.get("reply")
                    # 效果追踪：鱼发言后 60s 内的群消息都记为反应
                    if group in watch and m.attr == "friend":
                        watch[group]["reactions"].append({"sender": m.sender, "text": m.content[:80]})
                    if reply:
                        parts = resp.get("parts") or [reply]
                        log(f"  → 鱼回复({resp.get('mode')}, {len(parts)} 条气泡): {reply[:50]}")
                        # 引用优先用原始消息对象（若仍有效），不预先全表扫描；
                        # 对象已失效时 quote 会失败并自动退回普通发送
                        at = m.sender if "@" in getattr(m, "content", "") else None
                        for i, part in enumerate(parts):
                            if i > 0:
                                time.sleep(SEND_GAP)
                            send(wx, group, part, at=at if i == 0 else None,
                                 reply_to=m if i == 0 else None)
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
                # 进日志文件，而不只是控制台 stderr
                log(f"【{group}】轮询出错: {traceback.format_exc().strip().splitlines()[-1]}")
            elapsed = time.time() - cycle_start
            pt.report_slow()
            if elapsed > 20:
                log(f"⚠️ 本轮耗时 {elapsed:.0f}s（正常<5s）——窗口可能呆滞。"
                    "若持续出现：检查微信窗口是否被最小化、挂机宝是否锁屏；"
                    "Ctrl+C 无响应时用任务管理器结束 python.exe")
            heartbeat.write_text(str(time.time()), encoding="utf-8")  # 每轮写心跳
            time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
