# -*- coding: utf-8 -*-
"""示例插件：/ping 与 /时间。命中即答，不走 LLM。

插件协议（放 brain/plugins/ 下的 .py 文件即自动加载）：
  match(text: str) -> bool        返回这条消息是否归本插件处理
  handle(msg) -> str | None       返回回复文本；返回 None 则继续走主流程
msg 字段：group / sender / text / mention / image_b64 / ts
"""
import time


def match(text: str) -> bool:
    t = text.strip()
    return t in ("/ping", "ping") or t.startswith("/时间") or t == "现在几点"


def handle(msg) -> str | None:
    t = msg.text.strip()
    if t in ("/ping", "ping"):
        return "pong 🐟"
    now = time.strftime("%H:%M", time.gmtime(time.time() + 8 * 3600))
    return f"现在 {now}（东八区），你在想什么呢"
