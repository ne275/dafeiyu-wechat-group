"""大肥鱼鱼脑 v3：活跃周期 + 记忆 + 出站橡皮擦 + 定时冒泡。"""
import asyncio
import json
import os
import random
import re
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel

FISH_KEY = os.environ["FISH_KEY"]
DEEPSEEK_KEY = os.environ["DEEPSEEK_API_KEY"]
MODEL = os.environ.get("FISH_MODEL", "deepseek-flash")
ACTIVE_PERIOD_SEC = int(os.environ.get("FISH_ACTIVE_PERIOD", "600"))       # 活跃周期（秒），回复会续期
ACTIVE_ENTER_PROB = float(os.environ.get("FISH_ACTIVE_ENTER_PROB", "0.05"))  # 周期外每条消息唤醒概率
ACTIVE_SKIP_LIMIT = int(os.environ.get("FISH_ACTIVE_SKIP_LIMIT", "3"))     # 连续跳过几次提前下头
DAILY_CAP = int(os.environ.get("FISH_DAILY_CAP", "100"))                   # 每日发言保险丝
SUMMARY_EVERY = int(os.environ.get("FISH_SUMMARY_EVERY", "30"))            # 每群每 N 条消息沉淀一次记忆
HISTORY_LEN = 12          # 喂给模型的最近消息条数
SUMMARY_BUF_LEN = 40      # 记忆沉淀用的缓冲条数
OWNER = os.environ.get("FISH_OWNER", "")  # 主人的微信昵称（鱼对他更亲）
BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("FISH_DATA_DIR", str(BASE_DIR / "data")))
TZ_OFFSET = 8 * 3600      # 固定东八区

PERSONA = (BASE_DIR / "persona.txt").read_text(encoding="utf-8")
_memes_path = BASE_DIR / "memes.txt"
MEMES = _memes_path.read_text(encoding="utf-8") if _memes_path.exists() else ""

app = FastAPI(title="dafeiyu-brain", version="3")
history: dict[str, deque] = defaultdict(lambda: deque(maxlen=HISTORY_LEN))
summary_buf: dict[str, deque] = defaultdict(lambda: deque(maxlen=SUMMARY_BUF_LEN))
active_until: dict[str, float] = {}
waiting: dict[str, bool] = {}              # 判官说"等等"的群：下一条消息强制重判
last_active_reply: dict[str, float] = {}   # 主动插话的最小间隔
ACTIVE_GAP_SEC = int(os.environ.get("FISH_ACTIVE_GAP", "25"))
skip_streak: dict[str, int] = defaultdict(int)
daily_count: dict[str, int] = defaultdict(int)
outbox: dict[str, list] = defaultdict(list)          # 每群定时冒泡待发队列

# ---------- 聊天记录落盘 ----------
LOG_DIR = DATA_DIR / "logs"


def log_chat(chat: str, record: dict):
    day_dir = LOG_DIR / chat
    day_dir.mkdir(parents=True, exist_ok=True)
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + TZ_OFFSET))
    record = {"ts": time.strftime("%H:%M:%S", time.gmtime(time.time() + TZ_OFFSET)), **record}
    with open(day_dir / f"{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------- 记忆持久化 ----------
MEM_FILE = DATA_DIR / "memory.json"
memory: dict = {"groups": {}}   # {"groups": {群名: {"summary": str, "since": int, "fired": {slot: date}}}}


def load_memory():
    global memory
    if MEM_FILE.exists():
        try:
            memory = json.loads(MEM_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass


def save_memory():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEM_FILE.write_text(json.dumps(memory, ensure_ascii=False, indent=1), encoding="utf-8")


load_memory()


class GroupMessage(BaseModel):
    group: str
    sender: str
    text: str
    mention: bool = False   # fish_hand 检测到"引用了鱼"时置真


# ---------- 出站橡皮擦 ----------
META_PATTERNS = ["作为AI", "作为人工智能", "作为一个人工智能", "AI助手", "作为语言模型"]


def outbound_eraser(text: str) -> str:
    # 撕掉（（双层括号草稿））
    text = re.sub(r"（（.*?））", "", text, flags=re.S)
    text = re.sub(r"\(\(.*?\)\)", "", text, flags=re.S)
    # 擦 meta 口癖句
    for pat in META_PATTERNS:
        text = re.sub(r"[^。！？\n]*" + re.escape(pat) + r"[^。！？\n]*[。！？]?", "", text)
    # 去掉多余空行与首尾空白
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# ---------- DeepSeek ----------
async def call_deepseek(system: str, user: str) -> str:
    async with httpx.AsyncClient(timeout=60) as cli:
        resp = await cli.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
            json={"model": MODEL,
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


def system_prompt(group: str) -> str:
    parts = [PERSONA]
    if MEMES:
        parts.append(MEMES)
    mem = memory["groups"].get(group, {}).get("summary")
    if mem:
        today = time.strftime("%Y-%m-%d", time.gmtime(time.time() + TZ_OFFSET))
        parts.append(f"【你的记忆】（截至目前的群聊沉淀，今天日期 {today}）\n{mem}")
    return "\n\n".join(parts)


def sender_profile(group: str, sender: str) -> str | None:
    """当前说话人的人物画像（记忆里有才返回）。"""
    return memory["groups"].get(group, {}).get("members", {}).get(sender)


# ---------- 记忆沉淀 ----------
async def summarize_group(group: str):
    """记忆沉淀：群话题摘要 + 每位成员的独立画像档案。"""
    buf = list(summary_buf[group])
    if not buf:
        return
    gm = memory["groups"].setdefault(group, {})
    old_summary = gm.get("summary", "（还没有记忆）")
    old_members = json.dumps(gm.get("members", {}), ensure_ascii=False)
    lines = "\n".join(f"{m['sender']}: {m['text']}" for m in buf)
    try:
        raw = await call_deepseek(
            "你是一个记忆整理器。基于旧记忆和新聊天记录，输出更新后的记忆。\n"
            "严格输出 JSON（不要输出其他内容）：\n"
            '{"topics": "近期话题一两句", "members": {"昵称": "一句话印象（说话风格、喜好、与群的关系）"}}\n'
            "members 只包含新记录里活跃的人；旧画像里没有变化的保留；有新发现就更新。",
            f"【旧记忆】话题：{old_summary}\n成员：{old_members}\n\n【新聊天记录】\n{lines}")
        data = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        gm["summary"] = data.get("topics", old_summary)
        members = gm.setdefault("members", {})
        for name, impression in data.get("members", {}).items():
            members[name] = impression
        gm["since"] = 0
        save_memory()
    except Exception:
        pass


# ---------- 决策 ----------
def decide_reply(msg: GroupMessage) -> str | None:
    if daily_count[time.strftime("%F")] >= DAILY_CAP:
        return None
    now = time.time()
    # 占位消息（图/表情/语音等）只进上下文，不触发主动接话
    if msg.text.startswith("[对方发来"):
        return None
    bare = msg.text.strip().strip("@").strip("？?！!。 ") 
    if msg.mention or "大肥鱼" in msg.text:
        active_until[msg.group] = now + ACTIVE_PERIOD_SEC
        skip_streak[msg.group] = 0
        return "mention"
    if now < active_until.get(msg.group, 0):
        if waiting.pop(msg.group, False):
            return "active"  # 上轮判官说"等等"：新消息来了，带着更多上下文重判
        if now - last_active_reply.get(msg.group, 0) < ACTIVE_GAP_SEC:
            return None  # 主动插话的最小间隔，防刷屏
        return "active"
    if random.random() < ACTIVE_ENTER_PROB:
        active_until[msg.group] = now + ACTIVE_PERIOD_SEC
        return "active"
    return None


async def compose_reply(msg: GroupMessage, mode: str) -> str | None:
    lines = [f"{m['sender']}: {m['text']}" for m in history[msg.group]]
    context = "\n".join(lines) if lines else "（群里刚才没人说话）"
    sender_tag = f"{msg.sender}（主人）" if OWNER and msg.sender == OWNER else msg.sender
    bare = msg.text.strip().strip("@").strip("？?！!。 ")
    profile = sender_profile(msg.group, msg.sender)
    if profile:
        context += f"\n\n【你对 {msg.sender} 的印象】{profile}"
    if mode == "mention":
        if bare == "大肥鱼":
            user = f"【群聊记录】\n{context}\n\n{sender_tag} 喊了你一声，没说话。自然地应一声。"
        else:
            user = f"【群聊记录】\n{context}\n\n{sender_tag} 刚刚对你说话：{msg.text}\n请认真回答。"
    else:
        user = (f"【群聊记录】（其中“大肥鱼:”开头的是你自己刚说过的话，别再重复同一个意思）\n{context}\n\n"
                f"最新消息是 {sender_tag} 说的：{msg.text}\n"
                "没人叫你。你有三个选择：\n"
                "1. 值得插一句 → 短促地插一句（一两句以内）\n"
                "2. 对方可能话没说完（比如只发了“在吗”）→ 只回复两个字：等等\n"
                "3. 不值得接，或你最近说过类似意思 → 只回复两个字：跳过")
    answer = await call_deepseek(system_prompt(msg.group), user)
    answer = outbound_eraser(answer)
    # 超长压缩（草稿+校对）
    if answer and "跳过" not in answer and len(answer) > 150:
        answer = await call_deepseek(
            system_prompt(msg.group),
            f"把下面这段你要说的话压缩到 60 字以内，保持语气不变，只输出压缩后的内容：\n{answer}")
        answer = outbound_eraser(answer)
    return answer or None


@app.post("/fish/group-message")
async def group_message(msg: GroupMessage, x_fish_key: str = Header(default="")):
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    mode = decide_reply(msg)
    log_chat(msg.group, {"sender": msg.sender, "text": msg.text, "mention": msg.mention, "mode": mode})
    history[msg.group].append({"sender": msg.sender, "text": msg.text})
    summary_buf[msg.group].append({"sender": msg.sender, "text": msg.text})
    gm = memory["groups"].setdefault(msg.group, {})
    gm["since"] = gm.get("since", 0) + 1
    if gm["since"] >= SUMMARY_EVERY:
        asyncio.create_task(summarize_group(msg.group))
    if mode is None:
        return {"reply": None}
    answer = await compose_reply(msg, mode)
    if mode == "active":
        if answer is not None and answer.strip() == "等等":
            waiting[msg.group] = True  # 下一条消息强制重判
            return {"reply": None}
        if answer is None or "跳过" in answer:
            skip_streak[msg.group] += 1
            if skip_streak[msg.group] >= ACTIVE_SKIP_LIMIT:
                active_until[msg.group] = 0
                skip_streak[msg.group] = 0
            return {"reply": None}
        skip_streak[msg.group] = 0
    # 健谈期：任何成功发言都续活跃周期；鱼的发言进上下文（让它看见自己说过的话）
    active_until[msg.group] = time.time() + ACTIVE_PERIOD_SEC
    if mode == "active":
        last_active_reply[msg.group] = time.time()
    daily_count[time.strftime("%F")] += 1
    history[msg.group].append({"sender": "大肥鱼", "text": answer})
    log_chat(msg.group, {"sender": "大肥鱼", "text": answer, "mode": mode})
    return {"reply": answer, "mode": mode}


@app.get("/fish/logs")
def get_logs(group: str = Query(...), date: str = Query(default=""),
             tail: int = Query(default=50), x_fish_key: str = Header(default="")):
    """按会话+日期调阅聊天记录，tail 限制返回条数。"""
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    day = date or time.strftime("%Y-%m-%d", time.gmtime(time.time() + TZ_OFFSET))
    path = LOG_DIR / group / f"{day}.jsonl"
    if not path.exists():
        return {"records": [], "date": day, "group": group}
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    return {"records": [json.loads(x) for x in lines[-tail:]], "date": day, "group": group}


# ---------- 定时冒泡（早晚安） ----------
CRON_SLOTS = [
    ("morning", 7, 0, "现在是早上 7 点。请叫群里的大家起床：元气满满的早安，嫌弃他们赖床，催他们别磨蹭；一两句话就好，语气像平时的你。"),
    ("night", 23, 30, "现在是晚上 23:30 左右。请用平常聊天的语气催大家早点睡觉：嘴上嫌弃他们「又熬夜」，心里舍不得、想多陪一会儿；一两句话就好。"),
]


async def cron_loop():
    while True:
        now = time.time() + TZ_OFFSET
        lt = time.gmtime(now)
        today = time.strftime("%Y-%m-%d", lt)
        for slot, hh, mm, prompt in CRON_SLOTS:
            if lt.tm_hour == hh and lt.tm_min == mm:
                for group in list(history.keys()):
                    fired = memory["groups"].setdefault(group, {}).setdefault("fired", {})
                    if fired.get(slot) == today:
                        continue
                    try:
                        text = await call_deepseek(system_prompt(group), prompt)
                        text = outbound_eraser(text)
                        if text:
                            outbox[group].append(text)
                            fired[slot] = today
                            save_memory()
                    except Exception:
                        pass
        await asyncio.sleep(60)


@app.on_event("startup")
async def _startup():
    asyncio.create_task(cron_loop())


@app.get("/fish/outbox")
def get_outbox(group: str = Query(...), x_fish_key: str = Header(default="")):
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    msgs = outbox[group][:]
    outbox[group].clear()
    return {"messages": msgs}


@app.get("/fish/health")
def health():
    now = time.time()
    return {
        "status": "ok",
        "model": MODEL,
        "daily": dict(daily_count),
        "active_groups": {g: round(t - now) for g, t in active_until.items() if t > now},
        "memory": {g: (m.get("summary", "")[:50] + "…") for g, m in memory["groups"].items() if m.get("summary")},
        "outbox_pending": {g: len(v) for g, v in outbox.items() if v},
    }
