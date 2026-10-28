# 服务器侧部署（鱼脑）

鱼脑是一个 FastAPI 服务（Docker 单容器），对外只暴露 HTTPS 接口给"鱼手"调用。

## 1. 启动

```bash
cd brain
export FISH_KEY=$(openssl rand -hex 24)   # 鱼手与鱼脑之间的共享密钥，记下来
export DEEPSEEK_API_KEY=sk-你的DeepSeek密钥
docker compose up -d
curl http://127.0.0.1:6190/fish/health    # 应返回 {"status":"ok",...}
```

数据（记忆、聊天日志）持久化在 `brain/data/`。**备份这个目录 = 备份鱼的灵魂。**

## 2. 用 HTTPS 暴露（推荐走你已有的反代）

鱼脑只绑定 `127.0.0.1:6190`。不要直接对公网开端口——把它挂在你的 nginx/caddy 后面。
nginx 示例（加到你已有的 443 server 块里）：

```nginx
location /fish/ {
    proxy_pass http://127.0.0.1:6190;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_read_timeout 90s;
}
```

这样入口就是 `https://你的域名/fish/`，填进 hand/config.json 的 `brain_url`。

> 为什么强调走 443：很多云厂商安全组只放行 80/443，新开端口两头都要折腾。

## 3. 接口一览（都需要 `X-Fish-Key` 头）

| 接口 | 用途 |
|---|---|
| `POST /fish/group-message` | 鱼手上报群消息，返回 `{reply, mode}` 或 `{reply: null}` |
| `GET /fish/outbox?group=` | 鱼手轮询定时冒泡消息 |
| `GET /fish/logs?group=&date=&tail=` | 调阅聊天记录（排查用） |
| `GET /fish/health` | 健康检查（无需密钥） |

## 4. 升级

```bash
cd brain
docker compose up -d --build   # 改完代码后重建
```

记忆与日志在 data/ 卷里，重建不丢。
