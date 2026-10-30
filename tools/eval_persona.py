# -*- coding: utf-8 -*-
"""人格评估器：跑 tests/dialogue_cases.json 里的场景，打印鱼的回复供逐条分析。

用法：先启动本地鱼脑（FISH_KEY=testkey），再
  python tools/eval_persona.py [--brain http://127.0.0.1:6190/fish] [--key testkey] [--persona cute]
"""
import argparse
import json
from pathlib import Path

import requests

CASES = json.loads((Path(__file__).parent.parent / "tests" / "dialogue_cases.json").read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--brain", default="http://127.0.0.1:6190/fish")
    p.add_argument("--key", default="testkey")
    args = p.parse_args()

    for c in CASES:
        text = c["text"]
        # 需要 @ 的场景补上 @，模拟真实触发
        if c["id"] not in ("smalltalk", "emoji", "half"):
            text = "@大肥鱼 " + text
        try:
            r = requests.post(args.brain.rstrip("/") + "/group-message",
                              json={"group": f"评估-{c['id']}", "sender": "评测员", "text": text, "ts": "21:00"},
                              headers={"X-Fish-Key": args.key}, timeout=75)
            d = r.json()
        except Exception as e:
            d = {"reply": f"（调用失败 {e}）", "mode": "error"}
        print(f"【{c['id']}】{c['note']}")
        print(f"  输入: {text}")
        print(f"  模式: {d.get('mode')}")
        print(f"  回复: {d.get('reply')}")
        print()


if __name__ == "__main__":
    main()
