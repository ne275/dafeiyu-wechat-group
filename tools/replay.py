# -*- coding: utf-8 -*-
"""日志回放器：把真实群聊日志喂给鱼脑，看它"当时会说什么"。

用途：零打扰测试。群里不需要任何人配合，用他们说过的话的"录音"测试新版本。

用法：
  python tools/replay.py <日志文件.jsonl> [--brain http://127.0.0.1:6190/fish] [--key xxx] [--limit 100] [--chat 回放组名]

日志格式：brain/data/logs/<会话>/<日期>.jsonl（鱼脑 v3+ 自动生成）。
鱼的当日回复（sender=大肥鱼）会被跳过，只回放人类消息。

注意：回放会真实调用 LLM（每条命中的消息一次），100 条约几分钱。
"""
import argparse
import difflib
import json
import sys

import requests


def main():
    p = argparse.ArgumentParser()
    p.add_argument("logfile")
    p.add_argument("--brain", default="http://127.0.0.1:6190/fish")
    p.add_argument("--key", required=True, help="鱼脑 FISH_KEY")
    p.add_argument("--chat", default="回放组", help="回放用的会话名（隔离记忆，别用真群名）")
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args()

    records = []
    with open(args.logfile, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("sender") != "大肥鱼":  # 只回放人类消息
                records.append(r)
    records = records[: args.limit]
    print(f"回放 {len(records)} 条消息 → {args.brain}（会话名: {args.chat}）\n")

    replies = []
    stats = {"mention": 0, "active": 0, "silent": 0, "error": 0}
    for r in records:
        try:
            resp = requests.post(
                args.brain.rstrip("/") + "/group-message",
                json={"group": args.chat, "sender": r["sender"],
                      "text": r["text"], "mention": r.get("mention", False)},
                headers={"X-Fish-Key": args.key}, timeout=75,
            ).json()
        except Exception as e:
            print(f'{r["ts"]} {r["sender"]}: {r["text"][:40]}  →  ⚠️ {e}')
            stats["error"] += 1
            continue
        reply = resp.get("reply")
        if reply:
            stats[resp.get("mode", "active")] += 1
            replies.append(reply)
            print(f'{r["ts"]} {r["sender"]}: {r["text"][:40]}')
            print(f'         └─ 🐟({resp.get("mode")}): {reply[:80]}')
        else:
            stats["silent"] += 1

    print("\n===== 统计 =====")
    print(f"mention: {stats['mention']}  active: {stats['active']}  沉默: {stats['silent']}  错误: {stats['error']}")

    # 复读粗检：相邻两条鱼回复的相似度
    dup = 0
    for a, b in zip(replies, replies[1:]):
        if difflib.SequenceMatcher(None, a, b).ratio() > 0.6:
            dup += 1
    print(f"相邻回复高相似(>0.6)次数: {dup}（复读率指标，越低越好）")


if __name__ == "__main__":
    sys.exit(main())
