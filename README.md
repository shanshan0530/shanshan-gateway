# Shanshan Gateway

给新前端使用的轻量 OpenAI 兼容网关。它把新前端的聊天请求安全地转发给支持 OpenAI 格式的 Claude 中转站。

第一版刻意保持简单：不修改 Ombre Brain，也暂时不做世界书。v0.2 增加私人 Telegram 通道；v0.3 使用本地 SQLite 持久化 TG 短期上下文；v0.4 可通过 MCP 对原版 OB 做只读自动召回；v0.5 接入 Supabase 跨端连续记忆与 Eventide 临时状态；v0.6 为缺少原生记忆的新前端提供 Gateway 全记忆模式；v0.7 增加分批自动总结；v0.8 增加可控的 TG 主动心跳；v0.9 建立只读设备感知与隐私安全事件层；v0.10 增加跨端早间健康背景与防刷屏催睡。

## 路线

```text
橘瓣 ───── /v1 ──> Shanshan Gateway ──> Claude 中转站
新前端 ─ /memory/v1 ─> Shanshan Gateway ─> Claude 中转站
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

## v0.5 Supabase 连续记忆与 Eventide

- TG 收发的 user/assistant 消息同步写入橘瓣现有的 `chat_messages`；
- TG 回复前读取最近的 `memory_summaries` 与其他渠道对话，换端后仍能接住话题；
- `/v1/chat/completions` 与 TG 都会自动读取 Eventide 当前周期、短时事件和身体底色；
- Eventide 只以临时、定性状态注入，不向模型暴露原始数值，也不会把状态写成永久记忆；
- Supabase 超时或不可用时自动降级，不阻断橘瓣、TG 或上游回复；
- 橘瓣请求不额外注入 Supabase 历史，避免与橘瓣内置的进阶记忆重复。

Zeabur 服务需要增加：

```text
SUPABASE_URL=https://你的项目.supabase.co
SUPABASE_KEY=Supabase 的 publishable 或 anon key
ORANGECHAT_ASSISTANT_ID=橘瓣记录使用的 assistant_id
EVENTIDE_ASSISTANT_ID=景行
```

两个功能开关默认开启，可分别设置 `SUPABASE_CONTINUITY_ENABLED=false` 或 `EVENTIDE_CONTEXT_ENABLED=false` 随时回退。真实 Supabase Key 只放在 Zeabur 环境变量中。

## v0.6 新前端全记忆模式

橘瓣已经自行同步 Supabase，因此默认请求仍保持 v0.5 行为，不会重复存档。缺少原生记忆的新前端可以在自定义请求头中添加：

```json
{
  "X-Memory-Mode": "full",
  "X-Client-Name": "orange-island"
}
```

启用后，Gateway 会：

- 只保存当前最新的 user 消息，不重复导入前端每轮携带的完整历史；
- 在非流式或流式回复完成后保存完整 assistant 回复；
- 使用本轮消息指纹幂等去重，网络重试不会产生重复记录；
- 自动读取 Supabase 近期总结、其他渠道最近对话、OB 召回和 Eventide 状态；
- 任一记忆服务暂时失败时继续转发聊天，不阻塞回复。

如果前端支持动态会话 ID，可额外发送 `X-Conversation-ID`。若不支持，Gateway 会根据客户端名称、首条系统消息与首条用户消息生成稳定的匿名会话标识。请求头中的原始会话名称只参与哈希，不会写入数据库。

`X-Client-Name` 仅用于区分来源，可自行取名。不要给橘瓣现有连接添加 `X-Memory-Mode: full`，否则会与橘瓣自己的 Supabase 插件形成双重存档。

### 不支持自定义请求头的前端

如果前端只能填写 Base URL，可以直接使用专用入口：

```text
https://你的网关域名/memory/v1
```

这个入口会自动启用完整记忆模式，并将默认客户端名称设为 `orange-island`。API Key 与普通 `/v1` 入口相同。橘瓣仍使用普通 `/v1`，不要改到这个专用入口。

## v0.7 新前端分批自动总结

- 只处理 `/memory/v1` 写入且会话 ID 以 `gw:` 开头的新前端对话；
- 橘瓣原生消息、日记总结、向量和 `BAAI/bge-m3` 召回完全不修改；
- 默认每累计 24 条 user/assistant 消息，在回复完成后由后台生成一次摘要；
- 摘要写入现有 `memory_summaries`，之后可被 Gateway 跨端连续记忆读取；
- 使用数据库检查点与原子写入，重试和并发请求不会重复生成同一批总结；
- 总结失败只记录安全错误并等待下一轮重试，不阻塞聊天回复；
- 每 24 条消息增加一次非流式上游调用，可用环境变量关闭或调整阈值。

部署前需应用 `supabase/migrations/202607230002_add_gateway_auto_summary.sql` 与后续修正迁移。生产项目已应用时不需要重复执行。

## v0.8 Telegram 主动心跳

- 每 15 分钟进行一次本地条件检查，不会每次检查都调用模型；
- 读取 Supabase 中所有渠道最后一次 user 活动，正在橘瓣或新 App 聊天时不会误判为沉默；
- 连续 60 分钟没有 user 活动后允许主动联系；
- 普通冷却 90 分钟，Eventide 出现强烈状态或有效短时事件时缩短为 45 分钟；
- 每天最多主动发送 10 条，默认 `06:00–09:00`（`Asia/Taipei`）为安静时段；
- 生成主动消息时注入 TG 角色提示词、近期 Supabase 总结、跨端对话、TG 短期上下文和 Eventide；
- 成功发送的主动消息会写入 TG SQLite 与 Supabase，后续回复可以自然接续；
- 心跳开关、最后发送时间和每日计数保存在 TG SQLite，重部署后仍然有效；
- 任一记忆或生成服务临时失败时不会发送占位消息，也不会消耗当日次数。

TG 私聊命令：

```text
/heartbeat          查看状态与今日次数
/heartbeat on       开启自动心跳
/heartbeat off      暂停自动心跳
/heartbeat now      忽略沉默、冷却和安静时段，立即生成一条测试消息
```

## v0.9 设备感知基础层（观察模式）

- 从橘瓣现有的 `device_data` 只读获取最新两次同步，不修改插件和原始表；
- 兼容 `app_usage`、`notifications`、`health_data` 以 JSON 字符串存入 JSONB 的双层格式；
- 把无时区的设备时间按 `Asia/Taipei` 解释后统一转换为 UTC；
- 可识别位置区域、前台 App、设备事件和健康采样的变化；
- 对外事件只包含类别、级别、时间、摘要和密钥化指纹，不携带坐标、地址、App 名、通知正文或健康数值；
- 当前为 `shadow`：不注入聊天、不写 OB、不改变 Eventide，也不会触发 TG 主动消息；
- 每 15 分钟观察一次，只把最后处理行、事件类型、密钥化指纹与计数保存进现有 SQLite；
- 同一状态默认冷却 180 分钟，重复扫描和容器重启不会重复计为新的候选事件；
- 指纹明细只保留 7 天，SQLite 不保存坐标、地址、App 名、通知正文或健康数值；
- 影子观察默认开启；可随时设置 `DEVICE_PERCEPTION_ENABLED=false` 单独停用。

需要进行结构测试时可在部署环境开启：

```text
DEVICE_PERCEPTION_ENABLED=true
DEVICE_PERCEPTION_TIMEZONE=Asia/Taipei
DEVICE_PERCEPTION_CHECK_SECONDS=900
DEVICE_PERCEPTION_COOLDOWN_MINUTES=180
DEVICE_PERCEPTION_DB_PATH=/app/data/telegram.sqlite3
```

影子统计可通过受 `GATEWAY_API_KEY` 保护的接口查看：

```text
GET /api/perception/status
```

它只返回检查点、扫描次数和事件类型计数，不返回事件指纹或任何原始设备值。

## v0.10 早间健康背景与催睡

- 台湾时间 `06:00–12:00` 聊天时，只读取 `device_data` 最新一行健康快照；
- 默认超过 45 分钟未更新的数据不注入，避免旧数据被误当成当前状态；
- 兼容橘瓣把 `health_data` 以 JSON 字符串套在 JSONB 中的存储格式；
- 睡眠、心率、血氧、压力、步数等只作为当前模型调用的临时背景，不写进 TG SQLite；
- 提示模型不要逐项播报数字，也不要把每次回复变成健康报告；
- `01:00–06:00` 聊天时提供自然的休息引导，不依赖前端时间提醒提示词；
- 催睡窗口内暂停普通 TG 心跳，避免用户已经睡着后被随机主动消息叫醒；
- TG 只有在最近 30 分钟仍有跨端 user 活动时才主动催睡；
- 第一条后至少间隔 60 分钟，且必须检测到新的 user 活动才允许第二条；
- 每晚最多两条催睡提醒，计数和时间保存在现有 SQLite，重部署不会重置；
- 催睡消息沿用 TG 角色提示、跨端连续记忆、Eventide 和最新可用健康背景；
- 健康数据不可用或暂时过期时，聊天和催睡都会安全降级。

默认配置：

```text
SLEEP_REMINDER_ENABLED=true
SLEEP_REMINDER_START_HOUR=1
SLEEP_REMINDER_END_HOUR=6
SLEEP_REMINDER_RECENT_ACTIVITY_MINUTES=30
SLEEP_REMINDER_FOLLOWUP_MINUTES=60
SLEEP_REMINDER_MAX_PER_NIGHT=2

HEALTH_CONTEXT_ENABLED=true
HEALTH_CONTEXT_MORNING_START_HOUR=6
HEALTH_CONTEXT_MORNING_END_HOUR=12
HEALTH_CONTEXT_MAX_AGE_MINUTES=45
```

### 后续路线

- 自动总结之上的纠错和 OB 选择性长期写入；
- 景行自拍语义图库，后续升级为 Gateway 调用生图 API 的动态自拍。

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
| `TELEGRAM_HEARTBEAT_ENABLED` | 否 | 是否启动 TG 主动心跳，默认 true；可再用 TG 命令暂停 |
| `TELEGRAM_HEARTBEAT_CHECK_SECONDS` | 否 | 后台条件检查间隔，默认 900 秒 |
| `TELEGRAM_HEARTBEAT_SILENCE_MINUTES` | 否 | 允许首次主动联系前的沉默时间，默认 60 分钟 |
| `TELEGRAM_HEARTBEAT_COOLDOWN_MINUTES` | 否 | 普通状态下两次心跳最短间隔，默认 90 分钟 |
| `TELEGRAM_HEARTBEAT_STRONG_COOLDOWN_MINUTES` | 否 | Eventide 强烈状态下最短间隔，默认 45 分钟 |
| `TELEGRAM_HEARTBEAT_DAILY_LIMIT` | 否 | 每个本地日期最多主动发送条数，默认 10 |
| `TELEGRAM_HEARTBEAT_QUIET_START_HOUR` | 否 | 安静时段开始小时，默认 6 |
| `TELEGRAM_HEARTBEAT_QUIET_END_HOUR` | 否 | 安静时段结束小时，默认 9 |
| `TELEGRAM_HEARTBEAT_TIMEZONE` | 否 | 心跳日期和安静时段时区，默认 `Asia/Taipei` |
| `OMBRE_RECALL_ENABLED` | 否 | 是否启用 TG 回复前的原版 OB 只读召回，默认 false |
| `OMBRE_MCP_URL` | 否 | 原版 OB 的 MCP 地址，可带或不带 `/mcp` |
| `OMBRE_MCP_TOKEN` | 否 | 原版 OB 静态 Token，仅作为请求头发送 |
| `OMBRE_RECALL_MAX_RESULTS` | 否 | 每轮最多召回桶数，默认 3 |
| `OMBRE_RECALL_MAX_TOKENS` | 否 | OB 单次召回预算，默认 1600 |
| `OMBRE_RECALL_TIMEOUT_SECONDS` | 否 | OB 召回总超时，默认 20 秒 |
| `OMBRE_RECALL_MAX_CHARS` | 否 | 注入模型前的硬字符上限，默认 7000 |
| `OMBRE_RECALL_MIN_QUERY_CHARS` | 否 | 自动召回最短问题长度，默认 4 |
| `SUPABASE_URL` | 否 | Supabase 项目 URL；与 Key 同时配置后启用 |
| `SUPABASE_KEY` | 否 | Supabase publishable/anon key，仅放部署环境变量 |
| `ORANGECHAT_ASSISTANT_ID` | 否 | 橘瓣聊天记录使用的 assistant_id，用于跨端读写 |
| `EVENTIDE_ASSISTANT_ID` | 否 | Eventide 表中的角色 ID，默认 `景行` |
| `SUPABASE_CONTINUITY_ENABLED` | 否 | TG 是否读写 Supabase 连续记忆，默认 true |
| `EVENTIDE_CONTEXT_ENABLED` | 否 | 是否自动注入 Eventide 临时状态，默认 true |
| `SUPABASE_TIMEOUT_SECONDS` | 否 | 单次 Supabase 请求超时，默认 8 秒 |
| `SUPABASE_SUMMARY_LIMIT` | 否 | TG 每轮最多读取的近期总结数，默认 3 |
| `SUPABASE_RECENT_MESSAGE_LIMIT` | 否 | TG 每轮最多读取的跨渠道消息数，默认 8 |
| `GATEWAY_AUTO_SUMMARY_ENABLED` | 否 | 是否为 `gw:*` 新前端对话生成分批总结，默认 true |
| `GATEWAY_SUMMARY_MESSAGE_THRESHOLD` | 否 | 每批触发总结的消息条数，默认 24 |
| `GATEWAY_SUMMARY_MAX_TOKENS` | 否 | 自动总结单次最大输出预算，默认 1200 |
| `GATEWAY_SUMMARY_TIMEOUT_SECONDS` | 否 | 自动总结上游请求超时，默认 60 秒 |
| `DEVICE_PERCEPTION_ENABLED` | 否 | 是否启用只读设备感知影子层，默认 true |
| `DEVICE_PERCEPTION_TIMEZONE` | 否 | 无时区设备时间的解释时区，默认 `Asia/Taipei` |
| `DEVICE_PERCEPTION_CHECK_SECONDS` | 否 | 影子观察间隔，默认 900 秒 |
| `DEVICE_PERCEPTION_COOLDOWN_MINUTES` | 否 | 相同状态重新成为候选前的冷却，默认 180 分钟 |
| `DEVICE_PERCEPTION_DB_PATH` | 否 | 感知检查点 SQLite 路径，默认复用 `/app/data/telegram.sqlite3` |

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
