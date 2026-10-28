# dafeiyu-wechat-group 🐟

> 大肥鱼 · 微信群版：在**微信群**里养一条 DeepSeek 鲸鱼娘

> 在微信群里养一条 DeepSeek 鲸鱼娘：有人格、有记忆、会看上下文、会主动搭话，也知道什么时候闭嘴。

"大肥鱼"是 DeepSeek 蓝鲸 logo 的社区二创形象（非官方）。本项目把它带进**微信群**：
不注入微信、不碰协议、不破解任何东西——脑在服务器，手在一台 Windows 机器上像真人一样操作官方客户端。

```
┌─────────────────────────────┐         ┌──────────────────────────┐
│  服务器（Linux，鱼脑）         │         │  Windows 机器（鱼的手）     │
│  brain/  FastAPI + DeepSeek │ ◄HTTPS► │  hand/  wxauto 轮询脚本    │
│  · 人格卡 + 热梗词典          │  密钥    │  · 官方 PC 微信客户端      │
│  · 活跃周期决策               │         │  · 无注入、无协议、UI 自动化 │
│  · 记忆沉淀 / 聊天日志        │         │                          │
│  · 早晚安定时冒泡             │         │                          │
└─────────────────────────────┘         └──────────────────────────┘
```

## 为什么是"脑手分离"

微信群里做机器人只有三条物理路线：协议模拟（灰色，随时被封杀）、注入 Hook（高风险、锁版本）、**UI 自动化（本项目）**。
UI 自动化需要一个真实 Windows 桌面跑微信，但它没有任何"智能"——所以把智能全部放在你自己的服务器上，Windows 端只是一个几十行的哑终端。

## 能力清单

| 能力 | 说明 |
|---|---|
| 🎭 人格 | 社区打磨的鲸鱼娘人格卡（嘴硬心软、短句、咕噜），附热梗词典 |
| 🗣️ 群聊 | 叫"大肥鱼"必回；**引用鱼的话=追问免@**；光喊名字会应一声 |
| 🧠 记忆 | 每群定期沉淀【近期话题 + 成员印象】，注入后续对话；越养越懂你群 |
| 💬 主动搭话 | 活跃周期模型：被@唤醒 → 周期内 LLM 判官决定接不接 → 连续跳过自动"下头"；越聊越嗨，冷场退散 |
| 🙈 自知 | 看得见自己说过的话（不复读）；看不清图就承认（占位符不瞎编） |
| 🧽 出站橡皮擦 | （（双层括号））里的心里话会被撕掉；"作为AI"类出戏句自动擦除；超长自动压缩 |
| ⏰ 定时冒泡 | 每天早安 / 催睡，自动发群 |
| 📜 聊天日志 | 按 会话/日期 落盘（jsonl），带查询接口 |
| 🛡️ 安全阀 | 每日发言上限、主动插话最小间隔、共享密钥鉴权 |

## 快速开始

你需要：

1. 一台 Linux 服务器（跑鱼脑，本项目的 brain/）
2. 一台 Windows 机器（跑微信和鱼手：闲置电脑、挂机宝、云电脑均可）
3. 一个微信小号（**别用大号**，虽然 UI 自动化是低风险方案）
4. 一个 DeepSeek API key

```bash
# 服务器上
cd brain
FISH_KEY=$(openssl rand -hex 24) DEEPSEEK_API_KEY=sk-你的key docker compose up -d
# 把 6190 端口经你的 nginx/caddy 以 HTTPS 暴露（示例见 docs/deploy-server.md）

# Windows 上
pip install -r hand/requirements.txt
cp hand/config.example.json hand/config.json   # 填入 brain_url / fish_key / 群名
python hand/fish_hand.py
```

详细教程（含我们踩过的所有坑）：

- [服务器侧部署](docs/deploy-server.md)
- [Windows 侧部署（挂机宝实操版）](docs/deploy-windows.md)
- [配置参数参考](docs/config.md)
- [排障合集](docs/troubleshooting.md)

## 风险与边界（务必读）

- **微信不欢迎任何形式的自动化**。UI 自动化（模拟真人操作官方客户端）是风险最低的一档，但不是零。请使用小号，控制发言频率。
- 本项目**只读取你有权使用的账号与会话**，请勿用于营销、群发、骚扰或未经授权的数据收集。
- wxauto 免费版目前支持微信 PC ≤ 4.1.8.107，**装完微信第一件事是关闭自动更新**。
- 群聊消息会发送给 DeepSeek（或你配置的模型商）。告知群友鱼的存在，是最基本的尊重。

## 致谢

- 人格卡与热梗词典改编、设计灵感来自 [whyever77/dafeiyu-astrbot](https://github.com/whyever77/dafeiyu-astrbot)（QQ 版大肥鱼全家桶）
- 部分回复策略参考 [SAKURAfan1023/dafeiyu-bot](https://github.com/SAKURAfan1023/dafeiyu-bot)
- UI 自动化依赖 [wxauto](https://docs.wxauto.org)

## License

MIT（代码）· 人格卡与热梗词典为改编内容，原出处见 [NOTICE](NOTICE)
