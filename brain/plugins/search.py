# -*- coding: utf-8 -*-
"""联网搜索插件：/搜 xxx、查一下 xxx、搜搜 xxx → 返回 DuckDuckGo 结果摘要。"""
import re

import httpx


def match(text: str) -> bool:
    t = text.strip()
    return t.startswith(("/搜", "查一下", "搜搜", "搜索 "))


def _query(text: str) -> str:
    return re.sub(r"^(/搜|查一下|搜搜|搜索)\s*", "", text.strip())


def handle(msg) -> str | None:
    q = _query(msg.text)
    if not q:
        return "搜啥？说个关键词"
    try:
        r = httpx.get("https://lite.duckduckgo.com/lite/",
                      params={"q": q}, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        html = r.text
        # result-link 标题+链接，result-snippet 摘要
        links = re.findall(r'class="result-link"[^>]*>(.*?)</a>', html, re.S)
        snippets = re.findall(r'class="result-snippet"[^>]*>(.*?)</td>', html, re.S)
        if not links:
            return f"没搜到「{q}」相关结果，换个词试试"
        def clean(s):
            return re.sub(r"<[^>]+>", "", s).strip()
        out = [f"搜「{q}」前几名："]
        for i, title in enumerate(links[:3]):
            snip = clean(snippets[i])[:80] if i < len(snippets) else ""
            out.append(f"{i+1}. {clean(title)} — {snip}")
        return "\n".join(out)
    except Exception as e:
        return f"搜索抽风了（{e}），等会儿再试"
