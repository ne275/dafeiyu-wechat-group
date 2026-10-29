# -*- coding: utf-8 -*-
"""全套文件更新器：从 /dl/ 拉取最新版鱼手/看门狗/启动器/诊断工具。

start.bat 每次启动自动调用；也可手动 python update.py。
文件级哈希比对，没变就不动。下载失败的文件保留旧版，不阻断。
"""
import hashlib
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent
FILES = ["fish_hand.py", "watchdog.py", "update.py", "start.bat",
         "disconnect-safe.bat", "diag_session.py", "fish_debug.py"]
UPDATE_BASE = "https://你的域名/dl/"  # 部署时替换


def log(msg):
    print(f"[update] {msg}", flush=True)


def md5_bytes(b):
    return hashlib.md5(b).hexdigest()


def md5_file(p):
    return md5_bytes(p.read_bytes()) if p.exists() else ""


def main():
    for name in FILES:
        try:
            r = requests.get(UPDATE_BASE + name, timeout=25)
            if r.status_code != 200:
                continue
            target = BASE / name
            if md5_bytes(r.content) != md5_file(target):
                target.write_bytes(r.content)
                log(f"{name} 已更新")
        except Exception as e:
            log(f"{name} 更新失败（保留旧版）: {e}")


if __name__ == "__main__":
    main()
