from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping


_FULL_MEMORY_MODES = {"full", "gateway", "on", "true", "1"}
_CLIENT_NAME_PATTERN = re.compile(r"[^a-z0-9_-]+")


@dataclass(frozen=True)
class GatewayMemoryRequest:
    """Per-turn metadata for opt-in cross-frontend memory handling."""

    enabled: bool
    client_name: str
    conversation_id: str
    user_text: str
    transcript_fingerprint: str

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        headers: Mapping[str, str],
    ) -> "GatewayMemoryRequest":
        mode = str(headers.get("x-memory-mode") or "").strip().lower()
        enabled = mode in _FULL_MEMORY_MODES
        client_name = _client_name(headers.get("x-client-name"))
        messages = payload.get("messages")
        if not isinstance(messages, list):
            messages = []
        transcript_fingerprint = _hash_json(messages)
        conversation_id = _conversation_id(payload, headers, client_name, messages)
        return cls(
            enabled=enabled,
            client_name=client_name,
            conversation_id=conversation_id,
            user_text=_latest_user_text(messages),
            transcript_fingerprint=transcript_fingerprint,
        )

    def message_fingerprint(self, role: str, content: str) -> str:
        value = "\n".join(
            (
                self.client_name,
                self.conversation_id,
                self.transcript_fingerprint,
                role,
                content.strip(),
            )
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


class OpenAIStreamTextCollector:
    """Collect assistant text from OpenAI-compatible SSE without delaying chunks."""

    def __init__(self, max_chars: int = 200_000) -> None:
        self._line_buffer = b""
        self._parts: list[str] = []
        self._chars = 0
        self._max_chars = max_chars

    def feed(self, chunk: bytes) -> None:
        if not chunk or self._chars >= self._max_chars:
            return
        self._line_buffer += chunk
        if len(self._line_buffer) > 1_000_000 and b"\n" not in self._line_buffer:
            self._line_buffer = b""
            return
        lines = self._line_buffer.split(b"\n")
        self._line_buffer = lines.pop()
        for line in lines:
            self._consume_line(line)

    def finish(self) -> str:
        if self._line_buffer:
            self._consume_line(self._line_buffer)
            self._line_buffer = b""
        return "".join(self._parts).strip()

    def _consume_line(self, raw_line: bytes) -> None:
        line = raw_line.strip()
        if not line.startswith(b"data:"):
            return
        data = line[5:].strip()
        if not data or data == b"[DONE]":
            return
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        text = extract_stream_delta_text(payload)
        if not text:
            return
        remaining = self._max_chars - self._chars
        value = text[:remaining]
        self._parts.append(value)
        self._chars += len(value)


def extract_stream_delta_text(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    parts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if isinstance(delta, dict):
            parts.append(_content_text(delta.get("content")))
    return "".join(parts)


def extract_response_text(raw: bytes, max_chars: int = 200_000) -> str:
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if not isinstance(choices, list):
        return ""
    parts: list[str] = []
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if isinstance(message, dict):
            parts.append(_content_text(message.get("content")))
    return "\n".join(value for value in parts if value).strip()[:max_chars]


def _latest_user_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            return _content_text(message.get("content")).strip()[:100_000]
    return ""


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        value = item.get("text")
        if isinstance(value, str):
            parts.append(value)
        elif item.get("type") in {"text", "output_text"}:
            nested = item.get("content")
            if isinstance(nested, str):
                parts.append(nested)
    return "".join(parts)


def _conversation_id(
    payload: dict[str, Any],
    headers: Mapping[str, str],
    client_name: str,
    messages: list[Any],
) -> str:
    external_id = str(headers.get("x-conversation-id") or "").strip()
    if not external_id:
        for key in ("conversation_id", "session_id"):
            value = payload.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                external_id = str(value).strip()
                break
    metadata = payload.get("metadata")
    if not external_id and isinstance(metadata, dict):
        for key in ("conversation_id", "session_id", "thread_id"):
            value = metadata.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                external_id = str(value).strip()
                break

    if external_id:
        suffix = hashlib.sha256(external_id.encode("utf-8")).hexdigest()[:20]
    else:
        seed: list[Any] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") in {"system", "user"}:
                seed.append(message)
            if message.get("role") == "user":
                break
        suffix = _hash_json(seed)[:20]
    return f"gw:{client_name}:{suffix}"


def _client_name(value: Any) -> str:
    normalized = str(value or "frontend").strip().lower()[:40]
    normalized = _CLIENT_NAME_PATTERN.sub("-", normalized).strip("-_")
    return normalized or "frontend"


def _hash_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
