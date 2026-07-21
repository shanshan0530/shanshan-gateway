from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections import defaultdict
from typing import Any

import httpx

from .config import Settings
from .proxy import chat_completions_url, public_error_message
from .storage import ConversationStore


logger = logging.getLogger("shanshan-gateway.telegram")


class TelegramBridge:
    """Small private Telegram adapter using Bot API long polling."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._offset = 0
        self._volatile_histories: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._store: ConversationStore | None = None
        self._store_unavailable = False
        self._client: httpx.AsyncClient | None = None

    async def run(self) -> None:
        if not self.settings.telegram_enabled:
            logger.info("telegram bridge disabled: TELEGRAM_BOT_TOKEN is not configured")
            return

        base_url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}"
        timeout = httpx.Timeout(
            self.settings.telegram_poll_timeout_seconds + 10,
            connect=20.0,
        )
        async with httpx.AsyncClient(base_url=base_url, timeout=timeout) as client:
            self._client = client
            await self._prepare_long_polling()
            logger.info(
                "telegram bridge started authorized=%s",
                self.settings.telegram_authorized,
            )
            try:
                while True:
                    try:
                        updates = await self._get_updates()
                        for update in updates:
                            await self._handle_update(update)
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:  # keep the worker alive on transient API errors
                        logger.warning("telegram polling failed: %s", type(exc).__name__)
                        await asyncio.sleep(5)
            finally:
                self._client = None

    async def push(self, text: str) -> None:
        """Send a proactive message to the configured private user."""
        if not self.settings.telegram_enabled:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
        if not self.settings.telegram_authorized:
            raise RuntimeError("TELEGRAM_ALLOWED_USER_ID is not configured")
        if not text.strip():
            raise ValueError("message text is empty")

        if self._client is not None:
            await self._send_text(self.settings.telegram_allowed_user_id, text.strip())
            return

        base_url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}"
        async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
            response = await client.post(
                "/sendMessage",
                json={"chat_id": self.settings.telegram_allowed_user_id, "text": text.strip()},
            )
            if response.status_code >= 400:
                raise RuntimeError(f"Telegram API returned HTTP {response.status_code}")

    async def _prepare_long_polling(self) -> None:
        client = self._require_client()
        response = await client.post(
            "/deleteWebhook",
            json={"drop_pending_updates": False},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Telegram API returned HTTP {response.status_code}")

    async def _get_updates(self) -> list[dict[str, Any]]:
        client = self._require_client()
        response = await client.post(
            "/getUpdates",
            json={
                "offset": self._offset,
                "timeout": self.settings.telegram_poll_timeout_seconds,
                "allowed_updates": ["message"],
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Telegram API returned HTTP {response.status_code}")
        payload = response.json()
        updates = payload.get("result") if isinstance(payload, dict) else []
        if not isinstance(updates, list):
            return []
        for update in updates:
            if isinstance(update, dict) and isinstance(update.get("update_id"), int):
                self._offset = max(self._offset, update["update_id"] + 1)
        return [item for item in updates if isinstance(item, dict)]

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat")
        sender = message.get("from")
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return
        if chat.get("type") != "private":
            return

        chat_id = str(chat.get("id", ""))
        user_id = str(sender.get("id", ""))
        text = message.get("text")
        if not chat_id or not user_id or not isinstance(text, str):
            return
        text = text.strip()
        if not text:
            return

        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        if command in {"/start", "/id"}:
            if not self.settings.telegram_authorized:
                await self._send_text(
                    chat_id,
                    "连接的第一步完成啦。你的 Telegram 数字 ID 是：\n"
                    f"{user_id}\n\n"
                    "请把它填入 Zeabur 的 TELEGRAM_ALLOWED_USER_ID，然后重新部署。",
                )
            elif self._is_allowed(user_id):
                await self._send_text(chat_id, "连接正常。这里已经只属于你啦。")
            else:
                await self._send_text(chat_id, "这个机器人是私人使用的。")
            return

        if not self.settings.telegram_authorized:
            await self._send_text(chat_id, "请先发送 /id 完成私人白名单设置。")
            return
        if not self._is_allowed(user_id):
            await self._send_text(chat_id, "这个机器人是私人使用的。")
            return

        if command == "/reset":
            self._clear_history(chat_id)
            await self._send_text(chat_id, "当前 TG 短期对话已经清空。")
            return

        await self._send_action(chat_id, "typing")
        try:
            answer = await self._complete(chat_id, text)
        except Exception as exc:
            logger.warning("telegram completion failed: %s", type(exc).__name__)
            await self._send_text(chat_id, "刚才连接上游时出了点问题，请稍后再试一次。")
            return

        self._remember(chat_id, "user", text)
        self._remember(chat_id, "assistant", answer)
        await self._send_text(chat_id, answer)

    async def _complete(self, chat_id: str, user_text: str) -> str:
        messages: list[dict[str, str]] = []
        if self.settings.telegram_system_prompt:
            messages.append({"role": "system", "content": self.settings.telegram_system_prompt})
        messages.extend(self._recent_history(chat_id))
        messages.append({"role": "user", "content": user_text})

        payload = {
            "model": self.settings.upstream_model,
            "messages": messages,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.settings.upstream_api_key}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(self.settings.request_timeout_seconds, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(
                chat_completions_url(self.settings.upstream_base_url),
                headers=headers,
                json=payload,
            )
        if response.status_code >= 400:
            public_message = public_error_message(response.status_code, response.content)
            raise RuntimeError(public_message)

        data = response.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("upstream response has no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        answer = _content_to_text(content).strip()
        if not answer:
            raise RuntimeError("upstream response is empty")
        return answer

    def _remember(self, chat_id: str, role: str, content: str) -> None:
        store = self._conversation_store()
        if store is not None:
            try:
                store.append(chat_id, role, content)
                return
            except (OSError, sqlite3.Error):
                self._mark_store_unavailable()
        history = self._volatile_histories[chat_id]
        history.append({"role": role, "content": content})
        limit = self.settings.telegram_history_messages
        if len(history) > limit:
            del history[:-limit]

    def _recent_history(self, chat_id: str) -> list[dict[str, str]]:
        store = self._conversation_store()
        if store is not None:
            try:
                return store.recent(chat_id, self.settings.telegram_history_messages)
            except (OSError, sqlite3.Error):
                self._mark_store_unavailable()
        return list(self._volatile_histories.get(chat_id, []))

    def _clear_history(self, chat_id: str) -> None:
        store = self._conversation_store()
        if store is not None:
            try:
                store.clear(chat_id)
            except (OSError, sqlite3.Error):
                self._mark_store_unavailable()
        self._volatile_histories.pop(chat_id, None)

    def _conversation_store(self) -> ConversationStore | None:
        if self._store_unavailable:
            return None
        if self._store is None:
            try:
                self._store = ConversationStore(
                    self.settings.telegram_db_path,
                    self.settings.telegram_max_stored_messages,
                )
            except (OSError, sqlite3.Error):
                self._mark_store_unavailable()
                return None
        return self._store

    def _mark_store_unavailable(self) -> None:
        if not self._store_unavailable:
            logger.warning("telegram persistence unavailable; using process memory")
        self._store_unavailable = True
        self._store = None

    def _is_allowed(self, user_id: str) -> bool:
        return user_id == self.settings.telegram_allowed_user_id

    async def _send_action(self, chat_id: str, action: str) -> None:
        client = self._require_client()
        await client.post("/sendChatAction", json={"chat_id": chat_id, "action": action})

    async def _send_text(self, chat_id: str, text: str) -> None:
        client = self._require_client()
        for part in _split_telegram_text(text):
            response = await client.post("/sendMessage", json={"chat_id": chat_id, "text": part})
            if response.status_code >= 400:
                raise RuntimeError(f"Telegram API returned HTTP {response.status_code}")

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("telegram bridge is not running")
        return self._client


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def _split_telegram_text(text: str, limit: int = 4000) -> list[str]:
    value = text.strip()
    if not value:
        return ["（空消息）"]
    parts: list[str] = []
    while len(value) > limit:
        split_at = value.rfind("\n", 0, limit)
        if split_at < limit // 2:
            split_at = value.rfind(" ", 0, limit)
        if split_at < limit // 2:
            split_at = limit
        parts.append(value[:split_at].rstrip())
        value = value[split_at:].lstrip()
    if value:
        parts.append(value)
    return parts
