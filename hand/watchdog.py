# -*- coding: utf-8 -*-
"""大肥鱼看门狗（Python 版）：自动更新 + 拉起鱼手 + 卡死强杀重启。

全程无 PowerShell。鱼手的报错输出抓到 fish_error.log。
用法：python watchdog.py（或双击 start.bat）
"""
import hashlib
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = Path(__file__).parent
HAND = BASE / "fish_hand.py"
HEARTBEAT = BASE / "fish_heartbeat"
ERROR_LOG = BASE / "fish_error.log"
LOG = BASE / "watchdog.log"
UPDATE_URL = "https://你的域名/dl/fish_hand.py"  # 部署时替换为实际更新源
STALE_SEC = 150      # 心跳超时阈值（秒）
CHECK_EVERY = 15     # 巡视间隔（秒）


def log(msg):
    line = f"[watchdog] {time.strftime('%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def md5(p):
    return hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else ""


def update_hand():
    """拉起前自动更新鱼手；失败则用本地现有版本，不阻断启动。"""
    try:
        r = requests.get(UPDATE_URL, timeout=30)
        r.raise_for_status()
        tmp = BASE / "fish_hand.latest"
        tmp.write_bytes(r.content)
        if md5(tmp) != md5(HAND):
            tmp.replace(HAND)
            log("鱼手已更新到最新版")
        else:
            tmp.unlink(missing_ok=True)
    except Exception as e:
        log(f"更新检查失败（用现有版本继续）: {e}")


def main():
    log(f"看门狗上线，监视 {HAND}")
    while True:
        update_hand()
        HEARTBEAT.unlink(missing_ok=True)
        with open(ERROR_LOG, "a", encoding="utf-8") as err:
            err.write(f"\n===== {time.strftime('%F %T')} 启动 =====\n")
            err.flush()
            p = subprocess.Popen([sys.executable, str(HAND)], cwd=BASE, stderr=err)
        log(f"鱼手启动 PID={p.pid}（崩溃时的红色报错会留在 fish_error.log）")
        while p.poll() is None:
            time.sleep(CHECK_EVERY)
            if HEARTBEAT.exists():
                age = time.time() - HEARTBEAT.stat().st_mtime
                if age > STALE_SEC:
                    log(f"心跳超时 {int(age)}s，强杀重启")
                    p.kill()
        log(f"鱼手退出（code {p.returncode}），5s 后重启")
        time.sleep(5)


if __name__ == "__main__":
    main()
