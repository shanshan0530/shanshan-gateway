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
from .proxy import chat_completions_url, prepare_payload, public_error_message
from .telegram import TelegramBridge


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shanshan-gateway")

settings = Settings.from_env()
telegram_bridge = TelegramBridge(settings)
telegram_task: asyncio.Task[None] | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global telegram_task
    if settings.telegram_enabled:
        telegram_task = asyncio.create_task(telegram_bridge.run(), name="telegram-bridge")
    try:
        yield
    finally:
        if telegram_task is not None:
            telegram_task.cancel()
            try:
                await telegram_task
            except asyncio.CancelledError:
                pass
            telegram_task = None


app = FastAPI(title="Shanshan Gateway", version="0.2.0", lifespan=lifespan)
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
    return {"service": "shanshan-gateway", "version": "0.2.0", "status": "ok"}


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
            "version": "0.2.0",
            "missing_env": missing,
            "upstream_url_valid": url_ok,
            "upstream_host": _safe_host(normalized_url),
            "telegram": {
                "enabled": settings.telegram_enabled,
                "authorized": settings.telegram_authorized,
            },
        },
    )


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

    prepared = prepare_payload(payload, settings.upstream_model)
    logger.info(
        "chat request model=%s stream=%s messages=%d",
        settings.upstream_model,
        bool(prepared.get("stream")),
        len(prepared["messages"]),
    )
    return await forward_to_upstream(prepared)


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


async def forward_to_upstream(payload: dict[str, Any]) -> Response:
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
            _stream_and_close(upstream_response, client),
            status_code=upstream_response.status_code,
            media_type=upstream_response.headers.get("content-type", "text/event-stream"),
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    raw = await upstream_response.aread()
    content_type = upstream_response.headers.get("content-type", "application/json")
    await upstream_response.aclose()
    await client.aclose()
    return Response(raw, status_code=upstream_response.status_code, media_type=content_type)


async def _stream_and_close(
    upstream_response: httpx.Response,
    client: httpx.AsyncClient,
) -> AsyncIterator[bytes]:
    try:
        async for chunk in upstream_response.aiter_raw():
            yield chunk
    finally:
        await upstream_response.aclose()
        await client.aclose()


def _safe_host(url: str) -> str:
    if not url:
        return ""
    try:
        return httpx.URL(url).host or ""
    except Exception:
        return ""
