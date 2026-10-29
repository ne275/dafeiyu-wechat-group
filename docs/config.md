# 配置参数参考

## 鱼脑（环境变量，见 brain/docker-compose.yml）

| 变量 | 默认 | 说明 |
|---|---|---|
| `FISH_KEY` | **必填** | 与鱼手共享的密钥 |
| `DEEPSEEK_API_KEY` | **必填** | DeepSeek API key（兼容 OpenAI 协议，换 base 可接别家） |
| `FISH_MODEL` | `deepseek-flash` | 模型 |
| `FISH_ACTIVE_PERIOD` | `600` | 活跃周期秒数。被@/发言会续期；周期内每条消息由 LLM 判官决定接不接 |
| `FISH_ACTIVE_ENTER_PROB` | `0.05` | 周期外每条消息的随机唤醒概率 |
| `FISH_ACTIVE_GAP` | `25` | 连续两次主动插话的最小间隔（秒），防刷屏 |
| `FISH_ACTIVE_SKIP_LIMIT` | `3` | 判官连续说"跳过"几次后提前结束活跃周期 |
| `FISH_DAILY_CAP` | `100` | 每日发言保险丝 |
| `FISH_SUMMARY_EVERY` | `30` | 每群每 N 条消息沉淀一次记忆 |
| `FISH_OWNER` | 空 | 主人的群昵称。设了之后鱼对主人态度不同 |

## 鱼手（hand/config.json）

| 字段 | 说明 |
|---|---|
| `brain_url` | 鱼脑 HTTPS 入口，如 `https://example.com/fish` |
| `fish_key` | 与鱼脑 `FISH_KEY` 一致 |
| `groups` | 监听的会话名列表，**必须与微信里显示的一字不差**（含全角标点）。填好友昵称即为私聊 |
| `bot_name` | 鱼在群里的昵称，用于"引用鱼的话=喊它"的识别 |
| `poll_interval` | 轮询秒数，默认 3 |

## 决策逻辑速览

```
每条群消息：
├─ 提到"大肥鱼" 或 引用了鱼 → 必回（mention）+ 进入/续期活跃周期
├─ 活跃周期内 → LLM 判官决定接不接（连续 N 次"跳过"自动下头）
├─ 周期外 → 小概率随机苏醒
└─ 硬性约束：主动插话最小间隔、每日上限、占位消息（图/表情）不触发主动
```

## 人格与热梗

- `brain/personas/`：人格库，每个文件一个人格。当前内置：
  - `default.txt`：松弛群友风（零缓冲、去 AI 味）
  - `cute.txt`：20 岁清纯女大学生气质的鲸鱼娘（清爽略萌不幼态）
- `brain/memes.txt`：热梗词典，定期更新保持"听得懂新话"
- 运行中切换（立即生效，无需重启）：
  ```bash
  curl -X POST https://你的域名/fish/persona \
    -H "X-Fish-Key: $FISH_KEY" -H "Content-Type: application/json" \
    -d '{"name": "cute"}'
  ```
  查看当前与可选：`GET /fish/persona`。选择持久化在 data/persona_select.json。
- 新增人格：往 personas/ 丢一个 .txt 文件即可被列表发现。
