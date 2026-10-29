# -*- coding: utf-8 -*-
"""分发产物的纪律测试：Windows 目标机的编码与语法约束。

起因（两次生产事故）：
- watchdog.ps1 UTF-8 无 BOM 被 PS5.1 按 GBK 读 → 乱码
- disconnect-safe.bat UTF-8 中文被 cmd 按 GBK 读 → 命令炸裂

规矩：
- *.bat 必须纯 ASCII（cmd 无编码声明机制）
- *.ps1 若含中文必须 UTF-8 BOM（PS5.1 靠 BOM 识别）
- *.py 必须能编译（Python 读 UTF-8 无所谓控制台编码）
"""
import py_compile
from pathlib import Path

HAND = Path(__file__).parent.parent / "hand"


class TestBatAscii:
    def test_all_bat_files_pure_ascii(self):
        bats = list(HAND.glob("*.bat"))
        assert bats, "hand/ 下应有 .bat 文件"
        for f in bats:
            raw = f.read_bytes()
            try:
                raw.decode("ascii")
            except UnicodeDecodeError as e:
                raise AssertionError(f"{f.name} 含非 ASCII 字节（cmd 会按 GBK 误读）: {e}")


class TestPs1Encoding:
    def test_ps1_with_cjk_must_have_bom(self):
        for f in HAND.glob("*.ps1"):
            raw = f.read_bytes()
            has_cjk = any(ord(c) > 0x3000 for c in raw.decode("utf-8-sig"))
            if has_cjk:
                assert raw.startswith(b"\xef\xbb\xbf"), f"{f.name} 含中文但缺 UTF-8 BOM（PS5.1 会误读）"


class TestPythonCompiles:
    def test_all_py_compile(self):
        for f in HAND.glob("*.py"):
            py_compile.compile(str(f), doraise=True)
