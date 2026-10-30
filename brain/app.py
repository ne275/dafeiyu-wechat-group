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
SUMMARY_EVERY = int(os.environ.get("FISH_SUMMARY_EVERY", "50"))            # 每群每 N 条消息沉淀一次记忆
HISTORY_LEN = int(os.environ.get("FISH_HISTORY_LEN", "20"))  # 喂给模型的最近消息条数
SUMMARY_BUF_LEN = 40      # 记忆沉淀用的缓冲条数
OWNER = os.environ.get("FISH_OWNER", "")  # 主人的微信昵称（鱼对他更亲）
BASE_DIR = Path(__file__).parent
DATA_DIR = Path(os.environ.get("FISH_DATA_DIR", str(BASE_DIR / "data")))
TZ_OFFSET = 8 * 3600      # 固定东八区

BRAIN_VERSION = "4.11"  # 行为修改必须递增——/fish/health 里可验证

# 人格库：personas/<name>.txt；选择持久化在 data/persona_select.json，支持热切换
PERSONA_DIR = BASE_DIR / "personas"
DEFAULT_PERSONA = os.environ.get("FISH_PERSONA", "default")
_persona_cache: dict = {}


def persona_name() -> str:
    sel = DATA_DIR / "persona_select.json"
    if sel.exists():
        try:
            return json.loads(sel.read_text(encoding="utf-8"))["name"]
        except Exception:
            pass
    return DEFAULT_PERSONA


def get_persona() -> str:
    name = persona_name()
    path = PERSONA_DIR / f"{name}.txt"
    if not path.exists():  # 向后兼容：旧单文件 persona.txt
        path = BASE_DIR / "persona.txt"
    mtime = path.stat().st_mtime
    if _persona_cache.get("name") != name or _persona_cache.get("mtime") != mtime:
        _persona_cache.update({"name": name, "mtime": mtime, "text": path.read_text(encoding="utf-8")})
    return _persona_cache["text"]


PERSONA = None  # 已被人格库取代（保留符号防旧引用报错）
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
    image_b64: str = ""     # 可选：消息附带图片的 base64（视觉理解）
    ts: str = ""            # 鱼手捕捉时间（HH:MM，东八区）


class EffectReport(BaseModel):
    """鱼发言后一段时间内的群内反应（鱼手上报）。"""
    group: str
    reply: str
    reactions: list[dict] = []  # [{"sender":..., "text":...}]


def ddg_search(query: str, n: int = 3) -> str:
    """DuckDuckGo lite 搜索，返回摘要文本（供 Planner 工具调用）。"""
    try:
        r = httpx.get("https://lite.duckduckgo.com/lite/",
                      params={"q": query}, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        html = r.text
        links = re.findall(r"class=['\"]result-link['\"][^>]*>(.*?)</a>", html, re.S)
        snippets = re.findall(r"class=['\"]result-snippet['\"][^>]*>(.*?)</td>", html, re.S)
        def clean(s):
            return re.sub(r"<[^>]+>", "", s).strip()
        if not links:
            return "（没搜到结果）"
        return "；".join(f"{clean(t)}（{clean(snippets[i])[:60] if i < len(snippets) else ''}）" for i, t in enumerate(links[:n]))
    except Exception as e:
        return f"（搜索失败：{e}）"


async def tool_result(name: str, args: dict, msg) -> str:
    """Planner 工具统一分发。"""
    if name == "query_profile":
        return sender_profile(msg.group, args.get("name", "")) or "（没有这人的画像）"
    if name == "query_memory":
        return memory["groups"].get(msg.group, {}).get("summary") or "（还没有记忆）"
    if name == "web_search":
        return ddg_search(args.get("query", ""))
    if name == "browse_bilibili":
        await bilibili_watch(msg.group)
        w = memory["groups"].get(msg.group, {}).get("watched", [])
        if w:
            v = w[0]
            return f"你刷到了《{v['title']}》（UP主:{v['up']}），简介：{v['desc'][:100]}，热评：{v['comments'][:2]}，链接 https://www.bilibili.com/video/{v['bvid']}"
        return "（没刷到合适的）"
    return "（未知工具）"


# ---------- Planner 工具循环（active 模式） ----------
TOOLS = [
    {"type": "function", "function": {"name": "reply",
     "description": "在群里插一句话",
     "parameters": {"type": "object",
                    "properties": {"text": {"type": "string", "description": "要说的话，一两句以内"}},
                    "required": ["text"]}}},
    {"type": "function", "function": {"name": "skip",
     "description": "不接话，保持沉默", "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "wait",
     "description": "对方可能话没说完（比如只发了「在吗」），等下一条消息再判断",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "query_profile",
     "description": "查看你对某个群友的印象档案",
     "parameters": {"type": "object",
                    "properties": {"name": {"type": "string", "description": "群友昵称"}},
                    "required": ["name"]}}},
    {"type": "function", "function": {"name": "query_memory",
     "description": "查看这个群的近期话题记忆",
     "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {"name": "web_search",
     "description": "遇到不懂的、时事、新东西、不确定的事实时，联网搜索",
     "parameters": {"type": "object",
                    "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                    "required": ["query"]}}},
    {"type": "function", "function": {"name": "browse_bilibili",
     "description": "去 B 站逛一圈，按群近期话题挑个相关视频看看（被叫刷 B 站或想找视频时用）",
     "parameters": {"type": "object", "properties": {}}}},
]


async def call_deepseek_tools(messages: list) -> dict:
    resp = await deepseek_client().post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
        json={"model": MODEL, "messages": messages,
              "tools": TOOLS, "tool_choice": "auto"},
    )
    resp.raise_for_status()
    return resp.json()


async def planner_active(msg: GroupMessage, context: str, sender_tag: str) -> tuple[str, str | None]:
    """主动插话的 Planner 循环。返回 (action, text)，action ∈ reply/skip/wait。
    判断用瘦 prompt（不带人格卡/热梗，省 prefill）；决定说话后再用完整人格生成。"""
    judge_system = (
        "你在替一个群聊机器人做判断：群里每条消息决定【接话 / 沉默 / 等对方说完】。\n"
        "原则：不每条都接；对方半截话就等；和你无关的闲聊多数沉默。\n"
        + (f"【这个群的近期话题】\n{memory['groups'].get(msg.group, {}).get('summary')}\n\n"
           if memory["groups"].get(msg.group, {}).get("summary") else ""))
    messages = [
        {"role": "system", "content": judge_system},
        {"role": "user", "content": (
            f"【群聊记录】（其中“大肥鱼:”开头的是机器人自己刚说过的）\n{context}\n\n"
            f"最新消息是 {sender_tag} 说的：{msg.text}\n"
            "判断后必须做最终动作：reply（给出要说的大意）/ skip / wait。"
            "最多用 3 次查询工具。")},
    ]
    draft = None
    for _ in range(3):
        try:
            resp = await call_deepseek_tools(messages)
        except Exception:
            return "skip", None
        m = resp["choices"][0]["message"]
        if not m.get("tool_calls"):
            content = (m.get("content") or "").strip()
            if not content or "跳过" in content:
                return "skip", None
            if content == "等等":
                return "wait", None
            draft = content
            break
        messages.append(m)
        for tc in m["tool_calls"]:
            name = tc["function"]["name"]
            args = json.loads(tc["function"].get("arguments") or "{}")
            if name == "reply":
                draft = args.get("text", "")
                break
            if name == "skip":
                return "skip", None
            if name == "wait":
                return "wait", None
            result = await tool_result(name, args, msg)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        if draft is not None:
            break
    if draft is None:
        return "skip", None
    # 决定说了→用完整人格生成正式发言
    final = await call_deepseek(
        system_prompt(msg.group),
        f"【群聊记录】\n{context}\n\n{sender_tag} 刚说：{msg.text}\n"
        f"你决定插一句话，大意是：{draft}\n用你的口吻写出来，一两句以内，可以按 [[next]] 连发。")
    return "reply", outbound_eraser(final)


# ---------- 指标 ----------
def record_stats(mode: str, latency_ms: int, llm_ms: int):
    today = time.strftime("%F")
    st = memory.setdefault("stats", {}).setdefault(today, {"replies": 0, "mentions": 0, "actives": 0, "latencies": []})
    st["replies"] += 1
    st["mentions" if mode == "mention" else "actives"] += 1
    st["latencies"].append({"total": latency_ms, "llm": llm_ms})
    save_memory()


# ---------- 插件系统 ----------
PLUGIN_DIR = BASE_DIR / "plugins"
_plugins: list = []


def load_plugins():
    """加载 plugins/*.py。协议：模块提供 match(text)->bool 和 handle(msg)->str|None。
    命中即答（不走 LLM）。"""
    import importlib.util
    if not PLUGIN_DIR.exists():
        return
    for f in sorted(PLUGIN_DIR.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"fish_plugin_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "match") and hasattr(mod, "handle"):
                _plugins.append(mod)
        except Exception as e:
            print(f"[plugin] {f.name} 加载失败: {e}")


load_plugins()


# ---------- 出站橡皮擦 ----------
META_PATTERNS = [
    "作为AI", "作为人工智能", "作为一个人工智能", "AI助手", "作为语言模型",
    "综上所述", "总而言之", "值得注意的是", "对你有帮助",
    "有什么可以帮您", "这是个好问题", "我理解你的感受", "首先", "其次",
    "祝你", "加油！",
]


def split_bubbles(text: str) -> list[str]:
    """拆成多条气泡：[[next]] 协议 + 裸换行（模型偶尔不用协议直接换行）。
    代码块（``` 包围）保持整体不拆。"""
    parts = []
    for chunk in re.split(r"\[\[next\]\]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "```" in chunk:
            parts.append(chunk)  # 代码块不拆
        else:
            parts.extend(l.strip() for l in chunk.splitlines() if l.strip())
    return parts or ([text] if text else [])


def outbound_eraser(text: str) -> str:
    # 撕掉（（双层括号草稿））
    text = re.sub(r"（（.*?））", "", text, flags=re.S)
    text = re.sub(r"\(\(.*?\)\)", "", text, flags=re.S)
    # 剥掉草稿残渣的“说「...」”/「说“...”」外壳
    m = re.match(r'^\s*说\s*[“"「](.*)[”"」]\s*$', text.strip(), flags=re.S)
    if m:
        text = m.group(1).strip()
    # 擦 meta 口癖句
    for pat in META_PATTERNS:
        text = re.sub(r"[^。！？\n]*" + re.escape(pat) + r"[^。！？\n]*[。！？]?", "", text)
    # 去掉多余空行与首尾空白
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


# ---------- DeepSeek ----------
# 共享连接池：省掉每次调用的 TCP+TLS 握手（异地 0.5-1s）
_shared_client: httpx.AsyncClient | None = None


def deepseek_client() -> httpx.AsyncClient:
    global _shared_client
    if _shared_client is None:
        _shared_client = httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_keepalive_connections=4))
    return _shared_client


async def call_deepseek(system: str, user: str, image_b64: str = "") -> str:
    """调用 DeepSeek。image_b64 非空时走多模态消息（模型需支持图片输入）。"""
    if image_b64:
        user_content = [
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
        ]
    else:
        user_content = user
    resp = await deepseek_client().post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {DEEPSEEK_KEY}"},
        json={"model": MODEL,
              "messages": [{"role": "system", "content": system},
                           {"role": "user", "content": user_content}]},
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def system_prompt(group: str) -> str:
    now_str = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + TZ_OFFSET))
    parts = [get_persona(), f"【当前时间】{now_str}（东八区）", f"【你现在的状态】{mood_text()}"]
    if MEMES:
        parts.append(MEMES)
    learned = memory.get("jargon", {})
    if learned:
        terms = "；".join(f"{t}={m}" for t, m in list(learned.items())[:30])
        parts.append(f"【你在群里学会的黑话】（自然使用，别刻意刷）\n{terms}")
    watched = memory["groups"].get(group, {}).get("watched", [])
    if watched:
        lines = "\n".join(
            f"- {w['date']}《{w['title']}》（UP主:{w['up']}，{w['kw']}，链接 https://www.bilibili.com/video/{w['bvid']}）"
            for w in watched[:4])
        parts.append(
            f"【你最近逛 B 站刷到过的视频】\n{lines}\n"
            "（群友聊到相关话题时，可以自然提起『我前两天刷到过一个……』并分享链接；"
            "没人提就别硬推，别当成广告位。）")
    mem = memory["groups"].get(group, {}).get("summary")
    if mem:
        gm = memory["groups"].get(group, {})
        updated = gm.get("summary_time", "未知时间")
        parts.append(
            f"【你脑海里关于这个群的印象】（更新于 {updated}）\n{mem}\n"
            "（这些是你自己慢慢攒下的印象。聊到时像老朋友一样自然提起一两句，"
            "别背出来、别汇报，没人问也别主动秀。"
            "注意时间：太旧的印象可能已过期——比如别人几天前想吃的东西，现在未必还算数。）")
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
        gm["summary_time"] = time.strftime("%m-%d %H:%M", time.gmtime(time.time() + TZ_OFFSET))
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
    # 占位消息（图/表情/语音等）只进上下文，不触发主动接话；
    # 但带真实图片的（image_b64 非空）可以正常评估
    if msg.text.startswith("[对方发来") and not msg.image_b64:
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


async def planner_mention(msg: GroupMessage, context: str, sender_tag: str) -> str | None:
    """mention 的工具循环应答：可 web_search 查证、可 browse_bilibili 被叫刷 B 站。"""
    messages = [
        {"role": "system", "content": system_prompt(msg.group)},
        {"role": "user", "content": (
            f"【群聊记录】\n{context}\n\n{sender_tag} 对你说话：{msg.text}\n"
            "认真回答。遇到不懂或时事，先用 web_search 查再答；"
            "被要求逛 B 站/找视频时用 browse_bilibili。"
            "最后必须用 reply 工具给出你的回复（一两句，可 [[next]] 连发）。")},
    ]
    for _ in range(3):
        try:
            resp = await call_deepseek_tools(messages)
        except Exception:
            return None
        m = resp["choices"][0]["message"]
        if not m.get("tool_calls"):
            content = (m.get("content") or "").strip()
            if content:
                return outbound_eraser(content)
            break  # 空内容：跳出走兜底
        messages.append(m)
        for tc in m["tool_calls"]:
            name = tc["function"]["name"]
            args = json.loads(tc["function"].get("arguments") or "{}")
            if name == "reply":
                text = args.get("text", "").strip()
                if text:
                    return outbound_eraser(text)
                break
            result = await tool_result(name, args, msg)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
    # 兜底：不用工具，直接生成一句
    try:
        fallback = await call_deepseek(
            system_prompt(msg.group),
            f"{sender_tag} 对你说话：{msg.text}\n认真简短地回答。")
        return outbound_eraser(fallback) or None
    except Exception:
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
        return await planner_mention(msg, context, sender_tag)
    else:
        eff = memory["groups"].get(msg.group, {}).get("effects", [])
        if eff:
            last = eff[-1]
            feel = ("有人接你的话" if last["reactions"] else "没人接话") + ("，还有人@你" if last.get("mentioned") else "")
            context += f"\n\n【你上次发言的反响】你说「{last['reply']}」之后：{feel}。"
        user = (f"【群聊记录】（其中“大肥鱼:”开头的是你自己刚说过的话，别再重复同一个意思）\n{context}\n\n"
                f"最新消息是 {sender_tag} 说的：{msg.text}\n"
                "没人叫你。你有三个选择：\n"
                "1. 值得插一句 → 短促地插一句（一两句以内）\n"
                "2. 对方可能话没说完（比如只发了“在吗”）→ 只回复两个字：等等\n"
                "3. 不值得接，或你最近说过类似意思 → 只回复两个字：跳过")
    if msg.image_b64:
        user += "\n\n（这条消息带一张图片，就在上面，你看得到它。根据图片内容自然地回应，别描述得太正式。）"
    answer = await call_deepseek(system_prompt(msg.group), user, image_b64=msg.image_b64)
    answer = outbound_eraser(answer)
    # 超长压缩（草稿+校对），压缩后断尾兜底
    if answer and len(answer) > 150:
        compressed = await call_deepseek(
            system_prompt(msg.group),
            f"把下面这段话压缩到 60 字以内，保持语气，必须是完整句子，只输出压缩后的内容：\n{answer}")
        compressed = outbound_eraser(compressed)
        if compressed and compressed[-1] not in "。！？!?~…":
            # 截断不完整句：退到最后一个完整句末
            cut = max(compressed.rfind(p) for p in "。！？!?~…")
            compressed = compressed[:cut + 1] if cut >= 8 else answer[:150]
        if compressed:
            answer = compressed
    return answer or None


def build_active_context(msg: GroupMessage) -> tuple[str, str]:
    """active 模式的上下文与说话人标签（含画像与上次反响）。"""
    lines = [f"[{m.get('ts', '?')}] {m['sender']}: {m['text']}" for m in history[msg.group]]
    context = "\n".join(lines) if lines else "（群里刚才没人说话）"
    profile = sender_profile(msg.group, msg.sender)
    if profile:
        context += f"\n\n【你对 {msg.sender} 的印象】{profile}"
    eff = memory["groups"].get(msg.group, {}).get("effects", [])
    if eff:
        last = eff[-1]
        feel = ("有人接你的话" if last["reactions"] else "没人接话") + ("，还有人@你" if last.get("mentioned") else "")
        context += f"\n\n【你上次发言的反响】你说「{last['reply']}」之后：{feel}。"
    sender_tag = f"{msg.sender}（主人）" if OWNER and msg.sender == OWNER else msg.sender
    return context, sender_tag


@app.post("/fish/group-message")
async def group_message(msg: GroupMessage, x_fish_key: str = Header(default="")):
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    t0 = time.time()
    # 插件优先：命中即答，不走 LLM
    for plugin in _plugins:
        try:
            if plugin.match(msg.text):
                answer = plugin.handle(msg)
                if answer:
                    log_chat(msg.group, {"sender": msg.sender, "text": msg.text, "mode": "plugin"})
                    history[msg.group].append({"sender": msg.sender, "text": msg.text, "ts": msg.ts})
                    log_chat(msg.group, {"sender": "大肥鱼", "text": answer, "mode": "plugin"})
                    history[msg.group].append({"sender": "大肥鱼", "text": answer,
                                               "ts": time.strftime("%H:%M", time.gmtime(time.time() + TZ_OFFSET))})
                    return {"reply": answer, "mode": "plugin", "parts": split_bubbles(answer)}
        except Exception:
            continue
    mode = decide_reply(msg)
    log_chat(msg.group, {"sender": msg.sender, "text": msg.text, "mention": msg.mention, "mode": mode})
    low = msg.text.lower()
    if any(w in msg.text for w in ("可爱", "谢谢", "喜欢", "好耶", "爱你")):
        mood_event("praise")
    elif any(w in msg.text for w in ("笨", "傻", "滚", "蠢", "废物")):
        mood_event("roast")
    history[msg.group].append({"sender": msg.sender, "text": msg.text, "ts": msg.ts})
    summary_buf[msg.group].append({"sender": msg.sender, "text": msg.text, "ts": msg.ts})
    gm = memory["groups"].setdefault(msg.group, {})
    gm["since"] = gm.get("since", 0) + 1
    if gm["since"] >= SUMMARY_EVERY:
        asyncio.create_task(summarize_group(msg.group))
    if mode is None:
        return {"reply": None}
    if mode == "mention":
        t_llm = time.time()
        answer = await compose_reply(msg, mode)
        llm_ms = int((time.time() - t_llm) * 1000)
    else:
        # active：Planner 工具循环
        context, sender_tag = build_active_context(msg)
        t_llm = time.time()
        action, answer = await planner_active(msg, context, sender_tag)
        llm_ms = int((time.time() - t_llm) * 1000)
        if action == "wait":
            waiting[msg.group] = True  # 下一条消息强制重判
            return {"reply": None}
        if action == "skip" or not answer:
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
    mood_event("speak")
    latency_ms = int((time.time() - t0) * 1000)
    record_stats(mode, latency_ms, llm_ms)
    history[msg.group].append({"sender": "大肥鱼", "text": answer,
                               "ts": time.strftime("%H:%M", time.gmtime(time.time() + TZ_OFFSET))})
    log_chat(msg.group, {"sender": "大肥鱼", "text": answer, "mode": mode,
                         "latency_ms": latency_ms, "llm_ms": llm_ms})
    return {"reply": answer, "mode": mode, "parts": split_bubbles(answer)}


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


# ---------- 黑话学习（每日扫描日志） ----------
async def jargon_job():
    """扫描今日聊天日志，提取鱼不认识的新词，两次出现后正式学会。"""
    day = time.strftime("%Y-%m-%d", time.gmtime(time.time() + TZ_OFFSET))
    candidates = memory.setdefault("jargon_candidates", {})
    learned = memory.setdefault("jargon", {})
    known = set(learned.keys())
    for chat_dir in LOG_DIR.glob("*"):
        log_file = chat_dir / f"{day}.jsonl"
        if not log_file.exists():
            continue
        lines = [json.loads(x) for x in log_file.read_text(encoding="utf-8").splitlines()]
        human = [f"{r['sender']}: {r['text']}" for r in lines
                 if r.get("sender") not in ("大肥鱼",) and r.get("text")]
        if len(human) < 10:
            continue
        try:
            raw = await call_deepseek(
                "你是群聊黑话挖掘机。从聊天记录里找出【你可能不认识的新词/缩写/梗】"
                "（排除这些已知的：" + "、".join(list(known)[:50]) + "）。\n"
                "严格输出 JSON 数组（没有就输出 []）："
                '[{"term": "词", "meaning": "结合上下文推测的含义，一句话"}]',
                "\n".join(human[-80:]))
            items = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            for it in items:
                term, meaning = it.get("term", "").strip(), it.get("meaning", "").strip()
                if not term or term in learned:
                    continue
                c = candidates.setdefault(term, {"meaning": meaning, "count": 0})
                c["count"] += 1
                if c["count"] >= 2:        # 两次出现才正式学会（防误学）
                    learned[term] = c["meaning"]
                    del candidates[term]
            save_memory()
        except Exception:
            pass


# ---------- 情绪状态机 ----------
def mood() -> dict:
    return memory.setdefault("mood", {"valence": 0, "energy": 100})


def mood_event(kind: str):
    """事件影响情绪：praise 被夸 / roast 被怼 / speak 发言 / tick 自然恢复。"""
    m = mood()
    if kind == "praise":
        m["valence"] = min(100, m["valence"] + 6)
    elif kind == "roast":
        m["valence"] = max(-100, m["valence"] - 6)
    elif kind == "speak":
        m["energy"] = max(0, m["energy"] - 2)
    elif kind == "tick":
        m["energy"] = min(100, m["energy"] + 5)
    save_memory()


def mood_text() -> str:
    m = mood()
    v, e = m["valence"], m["energy"]
    hour = time.gmtime(time.time() + TZ_OFFSET).tm_hour
    feel = "不错" if v > 20 else "有点烦" if v < -20 else "一般"
    if hour >= 23 or hour < 7:
        energy = "深夜了，有点困"
    else:
        energy = "充沛" if e > 60 else "还行" if e > 30 else "有点累"
    return f"心情{feel}，{energy}"


# ---------- 自主日程（B 站等） ----------
async def bilibili_hot(n: int = 5) -> list[dict]:
    """拉 B 站热门视频（公开 API，无需登录）。"""
    try:
        resp = await deepseek_client().get(
            "https://api.bilibili.com/x/web-interface/ranking/v2",
            params={"rid": 0, "type": "all"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        items = resp.json().get("data", {}).get("list", [])[:n]
        return [{"title": v["title"], "up": v["owner"]["name"], "bvid": v["bvid"]} for v in items]
    except Exception:
        return []


async def bilibili_search(keyword: str, n: int = 3) -> list[dict]:
    """按关键词搜 B 站视频。"""
    try:
        resp = await deepseek_client().get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={"search_type": "video", "keyword": keyword},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        items = resp.json().get("data", {}).get("result", [])[:n]
        return [{"title": re.sub(r"<[^>]+>", "", v["title"]), "up": v["author"], "bvid": v["bvid"]} for v in items]
    except Exception:
        return []


async def bilibili_detail(bvid: str) -> dict:
    """视频简介 + 热评。"""
    out = {"desc": "", "comments": []}
    try:
        r = await deepseek_client().get("https://api.bilibili.com/x/web-interface/view",
                                        params={"bvid": bvid}, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        d = r.json().get("data", {})
        out["desc"] = d.get("desc", "")[:300]
        aid = d.get("aid")
        if aid:
            r2 = await deepseek_client().get("https://api.bilibili.com/x/v2/reply",
                                             params={"type": 1, "oid": aid, "ps": 3, "sort": 2},
                                             headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            replies = r2.json().get("data", {}).get("replies") or []
            out["comments"] = [c["content"]["message"][:100] for c in replies]
    except Exception:
        pass
    return out


async def bilibili_watch(group: str):
    """鱼按日程逛 B 站：从群近期话题提取关键词→搜相关视频→看详情热评→存『看过清单』。
    不主动发群（聊到相关话题时才提起）。"""
    gm = memory["groups"].setdefault(group, {})
    topic = gm.get("summary", "")
    vids = await bilibili_hot(8)
    if not vids:
        return
    # 让鱼从热门里挑一个和群话题相关的（B 站搜索接口有反爬，热门榜可用）
    lines = "\n".join(f"{i}.《{v['title']}》（UP主:{v['up']}）" for i, v in enumerate(vids))
    try:
        pick = await call_deepseek(
            f"群友最近在聊：{topic or '日常闲聊'}。从这些 B 站热门视频里挑一个最相关或最有趣的，"
            "只输出序号（0 起）。没有特别相关就挑你（大肥鱼）会好奇的那个。",
            lines)
        idx = int(re.search(r"\d+", pick).group())
        idx = min(idx, len(vids) - 1)
    except Exception:
        idx = 0
    v = vids[idx]
    detail = await bilibili_detail(v["bvid"])
    watched = gm.setdefault("watched", [])
    watched.insert(0, {
        "title": v["title"], "up": v["up"], "bvid": v["bvid"],
        "kw": "热门", "desc": detail["desc"], "comments": detail["comments"],
        "date": time.strftime("%m-%d", time.gmtime(time.time() + TZ_OFFSET)),
    })
    gm["watched"] = watched[:5]  # 只留最近 5 个
    save_memory()
    log_chat(group, {"type": "bilibili_watch", "title": v["title"]})


# ---------- 定时冒泡（早晚安） ----------
CRON_SLOTS = [
    ("morning", 7, 0, "现在是早上 7 点。请叫群里的大家起床：元气满满的早安，嫌弃他们赖床，催他们别磨蹭；一两句话就好，语气像平时的你。"),
    ("bilibili", 12, 30, ""),   # 午间逛 B 站
    ("bilibili", 20, 30, ""),   # 晚间逛 B 站
    ("night", 23, 30, "现在是晚上 23:30 左右。请用平常聊天的语气催大家早点睡觉：嘴上嫌弃他们「又熬夜」，心里舍不得、想多陪一会儿；一两句话就好。"),
]


async def cron_loop():
    while True:
        now = time.time() + TZ_OFFSET
        lt = time.gmtime(now)
        today = time.strftime("%Y-%m-%d", lt)
        # 情绪自然恢复（每小时 +5 精力）
        last_tick = memory.get("_mood_tick", 0)
        if time.time() - last_tick > 3600:
            memory["_mood_tick"] = time.time()
            mood_event("tick")
        # 黑话学习任务（每日 23:00）
        if lt.tm_hour == 23 and lt.tm_min == 0:
            fired_j = memory.setdefault("_cron", {})
            if fired_j.get("jargon") != today:
                fired_j["jargon"] = today
                save_memory()
                asyncio.create_task(jargon_job())
        for slot, hh, mm, prompt in CRON_SLOTS:
            if lt.tm_hour == hh and lt.tm_min == mm:
                for group in list(history.keys()):
                    fired = memory["groups"].setdefault(group, {}).setdefault("fired", {})
                    if fired.get(slot) == today:
                        continue
                    try:
                        if slot == "bilibili":
                            await bilibili_watch(group)  # 只存『看过清单』，不主动发群
                            fired[slot] = today
                            save_memory()
                        else:
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


@app.post("/fish/effect")
def report_effect(rep: EffectReport, x_fish_key: str = Header(default="")):
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    mentioned = any("大肥鱼" in r.get("text", "") for r in rep.reactions)
    gm = memory["groups"].setdefault(rep.group, {})
    effects = gm.get("effects", [])[-4:]
    effects.append({"reply": rep.reply[:60], "reactions": len(rep.reactions), "mentioned": mentioned})
    gm["effects"] = effects
    save_memory()
    log_chat(rep.group, {"type": "effect", "reply": rep.reply[:60],
                         "reactions": len(rep.reactions), "mentioned": mentioned})
    return {"ok": True}


@app.get("/fish/outbox")
def get_outbox(group: str = Query(...), x_fish_key: str = Header(default="")):
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    msgs = outbox[group][:]
    outbox[group].clear()
    return {"messages": msgs}


@app.get("/fish/stats")
def get_stats(x_fish_key: str = Header(default="")):
    """控制面板数据：今日指标 + 延迟分布 + 各群状态。"""
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    today = time.strftime("%F")
    st = memory.get("stats", {}).get(today, {"replies": 0, "mentions": 0, "actives": 0, "latencies": []})
    lats = [x["total"] for x in st.get("latencies", [])]
    lats_sorted = sorted(lats)
    p95 = lats_sorted[int(len(lats_sorted) * 0.95)] if lats_sorted else 0
    return {
        "today": today,
        "replies": st.get("replies", 0),
        "mentions": st.get("mentions", 0),
        "actives": st.get("actives", 0),
        "latency_avg_ms": round(sum(lats) / len(lats)) if lats else 0,
        "latency_p95_ms": p95,
        "active_groups": {g: round(t - time.time()) for g, t in active_until.items() if t > time.time()},
        "memory_groups": list(memory["groups"].keys()),
        "jargon_learned": len(memory.get("jargon", {})),
    }


@app.get("/fish/board")
def board():
    html = (BASE_DIR / "board.html")
    if html.exists():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(html.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="board.html not found")


@app.get("/fish/persona")
def list_personas(x_fish_key: str = Header(default="")):
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    available = sorted(p.stem for p in PERSONA_DIR.glob("*.txt")) if PERSONA_DIR.exists() else []
    return {"current": persona_name(), "available": available}


class PersonaSelect(BaseModel):
    name: str


@app.post("/fish/persona")
def switch_persona(sel: PersonaSelect, x_fish_key: str = Header(default="")):
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    if not (PERSONA_DIR / f"{sel.name}.txt").exists():
        raise HTTPException(status_code=404, detail=f"人格 {sel.name} 不存在")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "persona_select.json").write_text(
        json.dumps({"name": sel.name}, ensure_ascii=False), encoding="utf-8")
    return {"current": sel.name, "note": "立即生效，无需重启"}


@app.get("/fish/memory")
def get_memory(group: str = Query(...), x_fish_key: str = Header(default="")):
    """查看某群的完整记忆（话题、成员画像、效果追踪）。"""
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    gm = memory["groups"].get(group, {})
    return {"group": group, "summary": gm.get("summary", ""),
            "members": gm.get("members", {}), "effects": gm.get("effects", [])}


class MemoryDelete(BaseModel):
    group: str
    target: str = "all"   # all / summary / members / effects
    member: str = ""      # target=members 且指定成员时只删该成员画像


@app.post("/fish/memory/delete")
def delete_memory(req: MemoryDelete, x_fish_key: str = Header(default="")):
    if x_fish_key != FISH_KEY:
        raise HTTPException(status_code=403)
    gm = memory["groups"].get(req.group)
    if gm is None:
        return {"deleted": False, "reason": "该群无记忆"}
    if req.target == "all":
        memory["groups"].pop(req.group, None)
    elif req.target == "summary":
        gm["summary"] = ""
        gm["summary_time"] = ""
    elif req.target == "members":
        if req.member:
            gm.get("members", {}).pop(req.member, None)
        else:
            gm["members"] = {}
    elif req.target == "effects":
        gm["effects"] = []
    save_memory()
    return {"deleted": True, "group": req.group, "target": req.target, "member": req.member}


@app.get("/fish/health")
def health():
    now = time.time()
    return {
        "status": "ok",
        "version": BRAIN_VERSION,
        "model": MODEL,
        "daily": dict(daily_count),
        "active_groups": {g: round(t - now) for g, t in active_until.items() if t > now},
        "memory": {g: (m.get("summary", "")[:50] + "…") for g, m in memory["groups"].items() if m.get("summary")},
        "outbox_pending": {g: len(v) for g, v in outbox.items() if v},
    }
