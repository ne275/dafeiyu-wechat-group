# 排障合集（真实踩坑记录）

## 鱼没反应，先按这个顺序查

1. **脚本在跑吗**（窗口没关？）
2. **群名一字不差吗**（全角！半角!、结尾的句号、emoji，照抄群顶部标题）
3. **消息是脚本启动之后发的吗**（首轮只登记历史，不回复）
4. **日志里有没有 ⚠️**（403=密钥错；连接失败=网络/域名问题）
5. **叫"大肥鱼"了吗**（普通闲聊只有小概率接话，这是设计，不是故障）

## Windows / 挂机宝

| 症状 | 原因与解法 |
|---|---|
| `Add-WindowsCapability 无法下载源文件` | 精简版系统阉割了 Windows Update。装绿色版软件替代，别依赖系统组件 |
| `未能创建 SSL/TLS 安全通道` | PowerShell 5.1 默认 TLS 1.0。先跑 `[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12` |
| pip 下载超时/十几 KB | 直连 PyPI 慢。加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| PowerShell 里 curl 测中文返回空 | PS 5.1 请求体中文会变乱码，**用 Python 测，别用 PowerShell 测中文接口** |
| 手机切号后鱼掉线 | 微信机制：切号踢全端。小号需要常驻底座，见 deploy-windows.md 第 6 节 |
| 断开远程桌面后鱼死了 | 你点了"注销"。正确做法：直接点窗口 × 断开 |
| wxauto 读不到消息 | 微信版本超了。wxauto4 免费版 ≤ 4.1.8.107，装回钉版并关自动更新 |

## 鱼的行为问题

| 症状 | 原因与解法 |
|---|---|
| 同一意思复读好几遍 | v3.1 前的 bug（鱼看不见自己的话），升级鱼脑 |
| 对图片/表情瞎编内容 | 占位消息应只进上下文不触发回复，v3.1 已修 |
| 100 秒说 7 句 | 调大 `FISH_ACTIVE_GAP`（默认 25s） |
| 太冷漠从不插话 | 调大 `FISH_ACTIVE_ENTER_PROB`（默认 0.05）或 `FISH_ACTIVE_PERIOD` |
| 回复一大段 | 鱼脑会自动压缩到 60 字；还想更短改 persona.txt 里的聊天节奏 |
| 想让它记住的事转头就忘 | 记忆是"每 30 条消息沉淀一次"的慢记忆；查 `/fish/health` 的 memory 字段确认沉淀生效 |

## 紧急停止

```powershell
# 鱼手窗口按 Ctrl+C，鱼立刻闭嘴
```

```bash
# 服务器上，鱼脑停转（鱼手会报连接失败，无害）
docker compose -f brain/docker-compose.yml stop
```
