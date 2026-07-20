# Ombre 二改版 Zeabur 测试包装层

此目录只用于并行测试，不修改现有 Shanshan Gateway，也不会替换原版 Ombre Brain。

## 构建设置

- Branch: `ombre-zeabur-test`
- Dockerfile: `ombre-zeabur/Dockerfile`
- 对外端口: `8080`（容器内由 `PORT` 控制）
- 持久卷: `/app/data`

包装层锁定二改版提交：

`8bb06dda6c5b6df5ee27a081f92ca6c3fba59ec6`

## 最少环境变量

```env
OMBRE_API_KEY=用于总结/脱水模型的密钥
OMBRE_BASE_URL=对应 OpenAI 兼容地址
OMBRE_MODEL=便宜的小模型名

OMBRE_EMBEDDING_API_KEY=向量模型密钥
OMBRE_EMBEDDING_BASE_URL=向量接口地址
OMBRE_EMBEDDING_MODEL=向量模型名

OMBRE_GATEWAY_TOKEN=连接二改 Gateway 的密码
OMBRE_GATEWAY_UPSTREAM_API_KEY=Claude 中转站密钥
OMBRE_GATEWAY_UPSTREAM_BASE_URL=Claude 中转站 OpenAI 兼容 Base URL
OMBRE_GATEWAY_UPSTREAM_MODEL=真实 Claude 模型名
OMBRE_GATEWAY_UPSTREAM_MODELS=真实 Claude 模型名

OMBRE_AI_NAME=AI 名字
OMBRE_USER_NAME=珊珊
OMBRE_USER_DISPLAY_NAME=小狐狸
```

## 测试阶段默认关闭

- 自动 Dream
- 自动 Reflection
- 自动 Portrait
- Reranker

每日聊天记忆保持 `review`，不会直接自动写入正式长期记忆。

需要逐项开启时再设置：

```env
OMBRE_DREAM_AUTO_ENABLED=true
OMBRE_REFLECTION_AUTO_ENABLED=true
OMBRE_PORTRAIT_AUTO_ENABLED=true
OMBRE_RERANKER_ENABLED=true
```

## 地址

部署域名假设为 `https://example.zeabur.app`：

- Brain 健康检查：`/health`
- Gateway 健康检查：`/gateway-health`
- Gateway API：`/v1`
- Brain Dashboard/MCP：保持二改版原有路径

## 当前阶段禁止操作

- 不复制原版 `state`
- 不停原版 OB
- 不修改 Supabase
- 不把橘瓣正式流量切到测试服务

先确认空库服务、Gateway 和持久卷均正常，再进行记忆迁移。
