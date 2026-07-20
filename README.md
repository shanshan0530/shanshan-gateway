# Shanshan Gateway

给新前端使用的轻量 OpenAI 兼容网关。它把新前端的聊天请求安全地转发给支持 OpenAI 格式的 Claude 中转站。

第一版刻意保持简单：不保存聊天、不接数据库、不修改 Ombre Brain，也暂时不做世界书、心跳或欲望系统。

## 路线

```text
新前端 ── /v1 ──> Shanshan Gateway ──> Claude 中转站
新前端 ── /mcp ─────────────────────> Ombre Brain
Claude 官端 ── OAuth /mcp ──────────> Ombre Brain
```

## v0.1 功能

- `POST /v1/chat/completions`：流式及非流式转发；
- `GET /v1/models`：返回前端可选模型；
- `GET /health`：部署状态与配置检查；
- Bearer 或 `X-API-Key` 网关鉴权；
- 把前端模型别名映射到中转站真实模型名；
- 保留 OpenAI 兼容请求中的 messages、tools、多模态内容等字段；
- Base URL 可带或不带 `/v1`；
- 只对连接失败进行安全重试，避免流式内容重复；
- 不记录请求正文与任何密钥；
- 10 MiB 请求体上限，防止异常请求吃光内存。

## 一键部署到 Zeabur

仓库内的 `zeabur.yaml` 用于发布 Zeabur 模板。模板会自动：

- 从本仓库 `main` 分支部署；
- 创建并绑定 HTTP 域名；
- 生成随机 `GATEWAY_API_KEY`；
- 配置端口与健康检查；
- 提示填写中转站的 Base URL、API Key 和真实模型名。

部署完成后，新前端填写：

```text
Base URL: https://你的网关域名/v1
API Key: Zeabur 说明页显示的 Gateway API Key
模型名: shanshan-claude
```

如果暂时不发布模板，也可以在 Zeabur 选择本 GitHub 仓库直接部署。根目录的 `Dockerfile` 会被自动识别。

## 环境变量

| 变量 | 必填 | 用途 |
|---|---:|---|
| `GATEWAY_API_KEY` | 是 | 新前端连接网关时使用的密码 |
| `UPSTREAM_BASE_URL` | 是 | 中转站 OpenAI 兼容 Base URL |
| `UPSTREAM_API_KEY` | 是 | 中转站 API Key |
| `UPSTREAM_MODEL` | 是 | 中转站真实模型名 |
| `PUBLIC_MODEL_NAME` | 否 | 前端显示的模型名，默认 `shanshan-claude` |
| `REQUEST_TIMEOUT_SECONDS` | 否 | 上游请求超时，默认 300 秒 |
| `MAX_REQUEST_BYTES` | 否 | 最大请求体，默认 10 MiB |

真实密钥只放在 Zeabur 环境变量中，禁止写入仓库。

## 内存建议

个人使用从 **256 MB** 开始。部署后在 Zeabur 的网关服务中进入：

```text
Settings → Resources → Memory → 256 MB
```

保存后重新部署即可生效。如果 Metrics 中长期接近限制或出现 OOM，再提高到 512 MB。

## 本地运行与测试

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest -q
uvicorn app.main:app --reload
```

复制 `.env.example` 的变量到本地环境后，访问 `http://127.0.0.1:8000/health` 检查配置。

## 安全说明

- `/health` 不显示密钥或完整上游 URL，只显示主机名；
- `/v1/*` 必须通过网关鉴权；
- 中转站 Key 永远不会返回给新前端；
- 日志只记录模型名、流式开关和消息数量，不记录聊天内容。
