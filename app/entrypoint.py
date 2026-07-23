from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response

from .main import app, forward_to_upstream, require_auth, settings, supabase_bridge
from .proxy import prepare_payload
from .supabase import inject_system_context, render_continuity_context


logger = logging.getLogger("shanshan-gateway.continuity")


async def _telegram_continuity_context() -> str:
    """Read recent Telegram messages without writing the current frontend turn."""
    if (
        not settings.supabase_continuity_ready
        or not settings.telegram_allowed_user_id
    ):
        return ""

    conversation_id = f"tg:{settings.telegram_allowed_user_id}"
    try:
        messages = await supabase_bridge._select(
            "chat_messages",
            {
                "assistant_id": f"eq.{settings.orangechat_assistant_id}",
                "conversation_id": f"eq.{conversation_id}",
                "select": "role,content,conversation_id,created_at",
                "order": "created_at.desc",
                "limit": str(settings.supabase_recent_message_limit),
            },
        )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("Telegram continuity unavailable: %s", type(exc).__name__)
        return ""

    messages.reverse()
    context = render_continuity_context([], messages)
    return context.replace("【其他渠道最近对话】", "【Telegram 最近对话】", 1)


@app.get("/continuity/v1/models", dependencies=[Depends(require_auth)])
async def continuity_models() -> dict[str, Any]:
    return {
        "object": "list",
        "data": [
            {
                "id": settings.public_model_name,
                "object": "model",
                "created": 0,
                "owned_by": "shanshan-gateway",
            }
        ],
    }


@app.post("/continuity/v1/chat/completions", dependencies=[Depends(require_auth)])
async def continuity_chat_completions(request: Request) -> Response:
    """Proxy a frontend request while injecting recent Telegram context read-only."""
    missing = settings.missing_required()
    if missing:
        raise HTTPException(
            status_code=503,
            detail=f"服务端缺少环境变量：{', '.join(missing)}",
        )

    content_length = request.headers.get("content-length")
    if (
        content_length
        and content_length.isdigit()
        and int(content_length) > settings.max_request_bytes
    ):
        raise HTTPException(status_code=413, detail="请求体超过网关大小限制")

    body = await request.body()
    if len(body) > settings.max_request_bytes:
        raise HTTPException(status_code=413, detail="请求体超过网关大小限制")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="请求体不是有效 JSON") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        raise HTTPException(status_code=400, detail="messages 必须是数组")

    prepared = prepare_payload(payload, settings.upstream_model)
    telegram_context, eventide_context, wellbeing_context = await asyncio.gather(
        _telegram_continuity_context(),
        supabase_bridge.eventide_context(),
        supabase_bridge.wellbeing_context(),
    )
    inject_system_context(prepared, telegram_context)
    inject_system_context(prepared, eventide_context)
    inject_system_context(prepared, wellbeing_context)

    logger.info(
        "continuity request model=%s stream=%s messages=%d telegram_context=%s",
        settings.upstream_model,
        bool(prepared.get("stream")),
        len(prepared["messages"]),
        bool(telegram_context),
    )
    return await forward_to_upstream(prepared)
