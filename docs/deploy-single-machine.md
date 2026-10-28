# 单机模式（最简单，推荐没有服务器的人）

脑和手跑在**同一台 Windows 机器**上。不需要 Linux 服务器、域名、证书、反向代理——
鱼脑只监听 `127.0.0.1`，鱼手直接本机访问。

```
同一台 Windows 机器
┌────────────────────────────────────────┐
│  python -m uvicorn app:app --port 6190 │ ← 鱼脑（FastAPI，仅回环）
│  python fish_hand.py                   │ ← 鱼手（轮询微信）
│  微信 PC 客户端（小号，钉版）            │
└────────────────────────────────────────┘
            ↑ 出站调用 api.deepseek.com
```

## 1. 装 Python 依赖

```powershell
pip install fastapi uvicorn httpx wxauto4 requests -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 2. 启动鱼脑

```powershell
cd brain
$env:FISH_KEY = "随便生成一个长随机串"
$env:DEEPSEEK_API_KEY = "sk-你的key"
python -m uvicorn app:app --host 127.0.0.1 --port 6190
```

可选参数同样通过环境变量设置（见 config.md）。数据（记忆、日志）写在 `./data/`。

## 3. 配置并启动鱼手

`hand/config.json`：

```json
{
  "brain_url": "http://127.0.0.1:6190/fish",
  "fish_key": "和第2步相同的串",
  "groups": ["你的群名"],
  "bot_name": "大肥鱼",
  "poll_interval": 3
}
```

```powershell
cd hand
python fish_hand.py
```

## 4. 保活（开机自启）

在 `shell:startup`（开始菜单 → 运行 → 输入 `shell:startup`）里放两个快捷方式：

1. `python -m uvicorn app:app --host 127.0.0.1 --port 6190`（工作目录设为 brain/）
2. `python fish_hand.py`（工作目录设为 hand/）

配合微信的"开机自启 + 自动登录"，整台机器重启后鱼自动回来。

## 何时才需要分体（HTTPS 模式）

只有当你想**脑和手分开**（比如脑放在已有的 Linux 服务器上、手在另一台 Windows）时，
才需要 docs/deploy-server.md 里的域名 + 反代方案。单机模式下那些全部不需要。
