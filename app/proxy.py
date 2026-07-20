from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def chat_completions_url(base_url: str) -> str:
    """Normalize an OpenAI-compatible base URL to /v1/chat/completions."""
    raw = base_url.strip().rstrip("/")
    if not raw:
        raise ValueError("UPSTREAM_BASE_URL 不能为空")

    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("UPSTREAM_BASE_URL 必须是完整的 http(s) 地址")

    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        normalized_path = path
    elif path.endswith("/v1"):
        normalized_path = f"{path}/chat/completions"
    else:
        normalized_path = f"{path}/v1/chat/completions"

    return urlunsplit((parts.scheme, parts.netloc, normalized_path, parts.query, ""))


def prepare_payload(payload: dict[str, Any], upstream_model: str) -> dict[str, Any]:
    """Copy the request and map the public model alias to the real upstream model."""
    prepared = dict(payload)
    prepared["model"] = upstream_model
    return prepared


def public_error_message(status_code: int, upstream_body: bytes) -> str:
    """Return a bounded upstream error without logging or reflecting secrets."""
    text = upstream_body.decode("utf-8", "replace").strip()
    if len(text) > 2000:
        text = text[:2000] + "…"
    return text or f"上游接口返回 HTTP {status_code}"
