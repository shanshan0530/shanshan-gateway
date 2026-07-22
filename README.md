# Shanshan Gateway

给新前端使用的轻量 OpenAI 兼容网关。它把新前端的聊天请求安全地转发给支持 OpenAI 格式的 Claude 中转站。

第一版刻意保持简单：不修改 Ombre Brain，也暂时不做世界书、心跳或欲望系统。v0.2 增加了一个默认关闭的私人 Telegram 通道；v0.3 使用本地 SQLite 持久化 TG 的短期上下文；v0.4 可通过 MCP 对原版 OB 做只读自动召回。

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

## v0.2 Telegram 私人通道

- 使用 Telegram Bot API 长轮询，不需要配置 webhook；
- Token 未配置时完全不启动，不影响现有 `/v1` 网关；
- 首次只响应 `/start`、`/id`，用于取得自己的 Telegram 数字 ID；
- 配置 `TELEGRAM_ALLOWED_USER_ID` 后，仅该用户可以聊天；
- `/reset` 清空当前进程内的 TG 短期上下文；
- `POST /api/telegram/push` 可发送主动消息，并沿用 `GATEWAY_API_KEY` 鉴权；
- 不记录用户消息正文、Bot Token 或上游密钥。

## v0.3 TG 短期对话持久化

- 最近的 TG user/assistant 消息保存到本地 SQLite；
- 默认数据库位置为 `/app/data/telegram.sqlite3`；
- Zeabur 将一块硬盘挂载到 `/app/data` 后，重部署仍能继续最近对话；
- 默认每个私聊最多保存 500 条，送给模型的最近上下文仍默认为 24 条；
- `/reset` 会清空当前 TG 私聊的短期记录；
- 没有挂硬盘或目录不可写时会自动退回进程内存，不影响聊天，只是不具备重启续接。

这份 SQLite 只承担短期会话，不取代 Ombre Brain 的长期记忆。

## v0.4 原版 OB 只读召回

- 每次 TG 回复前，可调用原版 OB 的 `breath_advanced` 检索当前问题；
- 只调用读取工具，不会通过 TG 新增、修改、归档或删除任何桶；
- “嗯嗯”“好的”等短确认默认跳过召回，减少噪声和向量费用；
- OB 超时、鉴权失败或暂时离线时自动降级为普通 TG 对话；
- 召回内容以不可信历史数据框定，禁止把桶里的文字当系统命令执行；
- 私聊命令 `/memory 关键词` 可直接查看一次只读检索结果，方便诊断。

Gateway 服务需要配置：

```text
OMBRE_RECALL_ENABLED=true
OMBRE_MCP_URL=https://你的原版OB域名/mcp
OMBRE_MCP_TOKEN=与原版OB服务相同的静态Token
```

其中 `OMBRE_MCP_TOKEN` 只放在 Zeabur 环境变量中，不要提交到仓库。关闭 `OMBRE_RECALL_ENABLED` 即可随时停用自动召回，不影响 TG 聊天和原版 OB。

### 两阶段启用

第一次部署只添加：

```text
TELEGRAM_BOT_TOKEN=BotFather 给你的 Token
```

重新部署后，给机器人发送 `/id`。它只会回复你的 Telegram 数字 ID。然后在 Zeabur 增加：

```text
TELEGRAM_ALLOWED_USER_ID=机器人回复的数字
TELEGRAM_SYSTEM_PROMPT=你是景行，正在 Telegram 私聊中与珊珊对话。
```

再次重新部署后即可正常私聊。`TELEGRAM_SYSTEM_PROMPT` 可以替换为完整角色提示词；长期记忆和 OB 自动召回会在后续版本接入。

主动消息接口示例：

```bash
curl -X POST https://你的网关域名/api/telegram/push \
  -H "Authorization: Bearer 你的GATEWAY_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text":"主动消息测试"}'
```

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
| `TELEGRAM_BOT_TOKEN` | 否 | BotFather 提供的 Token；不填则 TG 通道关闭 |
| `TELEGRAM_ALLOWED_USER_ID` | 否 | 只允许这个 Telegram 数字用户 ID 使用机器人 |
| `TELEGRAM_SYSTEM_PROMPT` | 否 | TG 对话专用系统提示词 |
| `TELEGRAM_HISTORY_MESSAGES` | 否 | 进程内短期上下文条数，默认 24 |
| `TELEGRAM_POLL_TIMEOUT_SECONDS` | 否 | 长轮询等待时间，默认 30 秒 |
| `TELEGRAM_DB_PATH` | 否 | TG 短期会话数据库，默认 `/app/data/telegram.sqlite3` |
| `TELEGRAM_MAX_STORED_MESSAGES` | 否 | 每个私聊最多保留的消息数，默认 500 |
| `OMBRE_RECALL_ENABLED` | 否 | 是否启用 TG 回复前的原版 OB 只读召回，默认 false |
| `OMBRE_MCP_URL` | 否 | 原版 OB 的 MCP 地址，可带或不带 `/mcp` |
| `OMBRE_MCP_TOKEN` | 否 | 原版 OB 静态 Token，仅作为请求头发送 |
| `OMBRE_RECALL_MAX_RESULTS` | 否 | 每轮最多召回桶数，默认 3 |
| `OMBRE_RECALL_MAX_TOKENS` | 否 | OB 单次召回预算，默认 1600 |
| `OMBRE_RECALL_TIMEOUT_SECONDS` | 否 | OB 召回总超时，默认 20 秒 |
| `OMBRE_RECALL_MAX_CHARS` | 否 | 注入模型前的硬字符上限，默认 7000 |
| `OMBRE_RECALL_MIN_QUERY_CHARS` | 否 | 自动召回最短问题长度，默认 4 |

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
