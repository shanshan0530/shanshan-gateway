from __future__ import annotations

import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .config import Settings
from .gateway_memory import (
    GatewayMemoryRequest,
    OpenAIStreamTextCollector,
    extract_response_text,
)
from .ombre import OmbreRecallClient, format_memory_context
from .perception_observer import PerceptionObserver
from .proxy import chat_completions_url, prepare_payload, public_error_message
from .supabase import SupabaseBridge, inject_system_context
from .summarizer import GatewayAutoSummarizer
from .telegram import TelegramBridge


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shanshan-gateway")
VERSION = "0.11.0"

settings = Settings.from_env()
telegram_bridge = TelegramBridge(settings)
supabase_bridge = SupabaseBridge(settings)
ombre_recall = OmbreRecallClient(settings)
auto_summarizer = GatewayAutoSummarizer(settings, supabase_bridge)
perception_observer = PerceptionObserver(settings, supabase_bridge)
telegram_task: asyncio.Task[None] | None = None
perception_task: asyncio.Task[None] | None = None
background_tasks: set[asyncio.Task[Any]] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global perception_task, telegram_task
    if settings.telegram_enabled:
        telegram_task = asyncio.create_task(telegram_bridge.run(), name="telegram-bridge")
    if settings.device_perception_ready:
        perception_task = asyncio.create_task(
            perception_observer.run(), name="perception-shadow"
        )
    try:
        yield
    finally:
        for task in tuple(background_tasks):
            task.cancel()
        if background_tasks:
            await asyncio.gather(*tuple(background_tasks), return_exceptions=True)
        background_tasks.clear()
        if telegram_task is not None:
            telegram_task.cancel()
            try:
                await telegram_task
            except asyncio.CancelledError:
                pass
            telegram_task = None
        if perception_task is not None:
            perception_task.cancel()
            try:
                await perception_task
            except asyncio.CancelledError:
                pass
            perception_task = None


app = FastAPI(title="Shanshan Gateway", version=VERSION, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def require_auth(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    if not settings.gateway_api_key:
        raise HTTPException(status_code=503, detail="服务端尚未配置 GATEWAY_API_KEY")

    bearer = ""
    if authorization and authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    candidate = bearer or (x_api_key or "").strip()
    if not secrets.compare_digest(candidate, settings.gateway_api_key):
        raise HTTPException(status_code=401, detail="网关 API Key 错误")


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "shanshan-gateway", "version": VERSION, "status": "ok"}


@app.get("/health")
async def health() -> JSONResponse:
    missing = settings.missing_required()
    try:
        normalized_url = chat_completions_url(settings.upstream_base_url) if settings.upstream_base_url else ""
        url_ok = True
    except ValueError:
        normalized_url = ""
        url_ok = False

    ready = not missing and url_ok
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ok" if ready else "needs_config",
            "version": VERSION,
            "missing_env": missing,
            "upstream_url_valid": url_ok,
            "upstream_host": _safe_host(normalized_url),
            "telegram": {
                "enabled": settings.telegram_enabled,
                "authorized": settings.telegram_authorized,
                "heartbeat": {
                    "ready": settings.telegram_heartbeat_ready,
                    "silence_minutes": settings.telegram_heartbeat_silence_minutes,
                    "cooldown_minutes": settings.telegram_heartbeat_cooldown_minutes,
                    "strong_cooldown_minutes": settings.telegram_heartbeat_strong_cooldown_minutes,
                    "daily_limit": settings.telegram_heartbeat_daily_limit,
                    "quiet_hours": (
                        f"{settings.telegram_heartbeat_quiet_start_hour:02d}:00-"
                        f"{settings.telegram_heartbeat_quiet_end_hour:02d}:00"
                    ),
                },
            },
            "ombre_recall": {
                "enabled": settings.ombre_recall_enabled,
                "ready": settings.ombre_recall_ready,
            },
            "supabase": {
                "ready": settings.supabase_ready,
                "continuity": settings.supabase_continuity_ready,
                "eventide_context": settings.eventide_context_ready,
                "device_perception": {
                    "ready": settings.device_perception_ready,
                    "mode": "shadow",
                    "check_seconds": settings.device_perception_check_seconds,
                    "cooldown_minutes": settings.device_perception_cooldown_minutes,
                },
            },
            "gateway_memory": {
                "available": settings.supabase_continuity_ready,
                "mode_header": "X-Memory-Mode: full",
                "base_url_path": "/memory/v1",
                "auto_summary": settings.gateway_auto_summary_ready,
                "summary_message_threshold": settings.gateway_summary_message_threshold,
            },
            "wellbeing": {
                "morning_health": {
                    "ready": settings.health_context_ready,
                    "window": (
                        f"{settings.health_context_morning_start_hour:02d}:00-"
                        f"{settings.health_context_morning_end_hour:02d}:00"
                    ),
                    "max_age_minutes": settings.health_context_max_age_minutes,
                },
                "sleep_reminder": {
                    "ready": settings.telegram_sleep_reminder_ready,
                    "window": (
                        f"{settings.sleep_reminder_start_hour:02d}:00-"
                        f"{settings.sleep_reminder_end_hour:02d}:00"
                    ),
                    "recent_activity_minutes": (
                        settings.sleep_reminder_recent_activity_minutes
                    ),
                    "followup_minutes": settings.sleep_reminder_followup_minutes,
                    "max_per_night": settings.sleep_reminder_max_per_night,
                },
            },
        },
    )


@app.get("/memory/v1/models", dependencies=[Depends(require_auth)])
@app.get("/v1/models", dependencies=[Depends(require_auth)])
async def models() -> dict[str, Any]:
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


@app.post("/memory/v1/chat/completions", dependencies=[Depends(require_auth)])
@app.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
async def chat_completions(request: Request) -> Response:
    missing = settings.missing_required()
    if missing:
        raise HTTPException(status_code=503, detail=f"服务端缺少环境变量：{', '.join(missing)}")

    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > settings.max_request_bytes:
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

    memory_headers = dict(request.headers)
    if request.url.path.startswith("/memory/"):
        memory_headers["x-memory-mode"] = "full"
        memory_headers.setdefault("x-client-name", "orange-island")
    memory_request = GatewayMemoryRequest.from_payload(payload, memory_headers)
    if memory_request.enabled and memory_request.user_text:
        await supabase_bridge.store_message(
            role="user",
            content=memory_request.user_text,
            conversation_id=memory_request.conversation_id,
            fingerprint=memory_request.message_fingerprint(
                "user", memory_request.user_text
            ),
        )

    prepared = prepare_payload(payload, settings.upstream_model)
    if memory_request.enabled:
        continuity, eventide_context, wellbeing_context, recalled_memory = await asyncio.gather(
            supabase_bridge.continuity_context(
                exclude_conversation_id=memory_request.conversation_id
            ),
            supabase_bridge.eventide_context(),
            supabase_bridge.wellbeing_context(),
            ombre_recall.recall(memory_request.user_text),
        )
        inject_system_context(prepared, continuity)
        if recalled_memory:
            inject_system_context(prepared, format_memory_context(recalled_memory))
    else:
        eventide_context, wellbeing_context = await asyncio.gather(
            supabase_bridge.eventide_context(),
            supabase_bridge.wellbeing_context(),
        )
    inject_system_context(prepared, eventide_context)
    inject_system_context(prepared, wellbeing_context)
    logger.info(
        "chat request model=%s stream=%s messages=%d memory_mode=%s client=%s",
        settings.upstream_model,
        bool(prepared.get("stream")),
        len(prepared["messages"]),
        "full" if memory_request.enabled else "frontend",
        memory_request.client_name,
    )
    return await forward_to_upstream(
        prepared,
        memory_request=memory_request if memory_request.enabled else None,
    )


@app.post("/api/telegram/push", dependencies=[Depends(require_auth)])
async def telegram_push(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="请求体不是有效 JSON") from exc
    text = payload.get("text") if isinstance(payload, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=400, detail="text 必须是非空字符串")
    if len(text) > 20_000:
        raise HTTPException(status_code=413, detail="Telegram 主动消息过长")
    try:
        await telegram_bridge.push(text)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return JSONResponse({"ok": True})


@app.get("/api/perception/status", dependencies=[Depends(require_auth)])
async def perception_status() -> JSONResponse:
    state = perception_observer.status()
    return JSONResponse(
        {
            "ready": settings.device_perception_ready,
            "mode": "shadow",
            "last_row_id": state.last_row_id if state is not None else 0,
            "last_checked_at": (
                state.last_checked_at.isoformat() if state and state.last_checked_at else None
            ),
            "total_scans": state.total_scans if state is not None else 0,
            "total_detected_events": (
                state.total_detected_events if state is not None else 0
            ),
            "total_eligible_events": (
                state.total_eligible_events if state is not None else 0
            ),
            "event_counts": state.event_counts if state is not None else {},
        }
    )


async def forward_to_upstream(
    payload: dict[str, Any],
    *,
    memory_request: GatewayMemoryRequest | None = None,
) -> Response:
    try:
        url = chat_completions_url(settings.upstream_base_url)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    headers = {
        "Authorization": f"Bearer {settings.upstream_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if payload.get("stream") else "application/json",
    }
    timeout = httpx.Timeout(settings.request_timeout_seconds, connect=30.0)
    transport = httpx.AsyncHTTPTransport(retries=2)
    client = httpx.AsyncClient(timeout=timeout, transport=transport, follow_redirects=False)
    try:
        upstream_request = client.build_request("POST", url, headers=headers, json=payload)
        upstream_response = await client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("upstream connection failed: %s", type(exc).__name__)
        raise HTTPException(status_code=502, detail=f"无法连接中转站：{type(exc).__name__}") from exc

    if upstream_response.status_code >= 400:
        raw = await upstream_response.aread()
        await upstream_response.aclose()
        await client.aclose()
        logger.warning("upstream returned status=%d", upstream_response.status_code)
        return JSONResponse(
            status_code=upstream_response.status_code,
            content={
                "error": {
                    "message": public_error_message(upstream_response.status_code, raw),
                    "type": "upstream_error",
                }
            },
        )

    if payload.get("stream"):
        return StreamingResponse(
            _stream_and_close(upstream_response, client, memory_request),
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type", "text/event-stream"),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    raw = await upstream_response.aread()
    content_type = upstream_response.headers.get("content-type", "application/json")
    await upstream_response.aclose()
    await client.aclose()
    if memory_request is not None:
        assistant_text = extract_response_text(raw)
        if assistant_text:
            stored = await supabase_bridge.store_message(
                role="assistant",
                content=assistant_text,
                conversation_id=memory_request.conversation_id,
                fingerprint=memory_request.message_fingerprint(
                    "assistant", assistant_text
                ),
            )
            if stored:
                schedule_auto_summary(memory_request.conversation_id)
    return Response(raw, status_code=upstream_response.status_code, media_type=content_type)


async def _stream_and_close(
    upstream_response: httpx.Response,
    client: httpx.AsyncClient,
    memory_request: GatewayMemoryRequest | None = None,
) -> AsyncIterator[bytes]:
    collector = OpenAIStreamTextCollector() if memory_request is not None else None
    completed = False
    try:
        async for chunk in upstream_response.aiter_raw():
            if collector is not None:
                collector.feed(chunk)
            yield chunk
        completed = True
    finally:
        await upstream_response.aclose()
        await client.aclose()
        if completed and collector is not None and memory_request is not None:
            assistant_text = collector.finish()
            if assistant_text:
                stored = await supabase_bridge.store_message(
                    role="assistant",
                    content=assistant_text,
                    conversation_id=memory_request.conversation_id,
                    fingerprint=memory_request.message_fingerprint(
                        "assistant", assistant_text
                    ),
                )
                if stored:
                    schedule_auto_summary(memory_request.conversation_id)


def schedule_auto_summary(conversation_id: str) -> None:
    if not settings.gateway_auto_summary_ready:
        return
    task = asyncio.create_task(
        auto_summarizer.maybe_summarize(conversation_id),
        name="gateway-auto-summary",
    )
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


def _safe_host(url: str) -> str:
    if not url:
        return ""
    try:
        return httpx.URL(url).host or ""
    except Exception:
        return ""
