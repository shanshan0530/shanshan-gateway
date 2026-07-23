from __future__ import annotations

import asyncio
import html
import logging
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from .config import Settings
from .ombre import OmbreRecallClient, format_memory_context
from .proxy import chat_completions_url, public_error_message
from .storage import ConversationStore, HeartbeatState
from .supabase import SupabaseBridge, inject_system_context


logger = logging.getLogger("shanshan-gateway.telegram")


_TELEGRAM_ACTION_RE = re.compile(
    r"(?P<prefix>^|[\s（(。！？!?，,:：；;])\*(?P<action>[^*\n]+?)\*(?=$|[\s）)。,，！？!?：:；;])",
    re.MULTILINE,
)


class TelegramBridge:
    """Small private Telegram adapter using Bot API long polling."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._offset = 0
        self._volatile_histories: dict[str, list[dict[str, str]]] = defaultdict(list)
        self._store: ConversationStore | None = None
        self._store_unavailable = False
        self._client: httpx.AsyncClient | None = None
        self._ombre = OmbreRecallClient(settings)
        self._supabase = SupabaseBridge(settings)
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._heartbeat_lock = asyncio.Lock()
        self._volatile_heartbeat_states: dict[str, HeartbeatState] = {}

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
            if self.settings.telegram_heartbeat_ready:
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat_loop(),
                    name="telegram-heartbeat",
                )
            logger.info(
                "telegram bridge started authorized=%s heartbeat=%s",
                self.settings.telegram_authorized,
                self.settings.telegram_heartbeat_ready,
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
                if self._heartbeat_task is not None:
                    self._heartbeat_task.cancel()
                    try:
                        await self._heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    self._heartbeat_task = None
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

        if command == "/memory":
            query = text.split(maxsplit=1)[1].strip() if " " in text else ""
            if not query:
                await self._send_text(chat_id, "用法：/memory 想查找的记忆")
                return
            await self._send_action(chat_id, "typing")
            memory = await self._ombre.recall(query, force=True)
            await self._send_text(
                chat_id,
                memory or "这次没有找到足够相关的 OB 记忆。",
            )
            return

        if command == "/heartbeat":
            await self._handle_heartbeat_command(chat_id, text)
            return

        await self._send_action(chat_id, "typing")
        conversation_id = f"tg:{chat_id}"
        await self._supabase.store_message(
            role="user", content=text, conversation_id=conversation_id
        )
        try:
            answer = await self._complete(chat_id, text)
        except Exception as exc:
            logger.warning("telegram completion failed: %s", type(exc).__name__)
            await self._send_text(chat_id, "刚才连接上游时出了点问题，请稍后再试一次。")
            return

        self._remember(chat_id, "user", text)
        self._remember(chat_id, "assistant", answer)
        await self._supabase.store_message(
            role="assistant", content=answer, conversation_id=conversation_id
        )
        await self._send_text(chat_id, answer)

    async def _handle_heartbeat_command(self, chat_id: str, text: str) -> None:
        argument = text.split(maxsplit=1)[1].strip().lower() if " " in text else ""
        if argument in {"on", "开启", "开"}:
            self._set_heartbeat_enabled(chat_id, True)
            await self._send_text(chat_id, "后台心跳已开启。")
            return
        if argument in {"off", "关闭", "关"}:
            self._set_heartbeat_enabled(chat_id, False)
            await self._send_text(chat_id, "后台心跳已暂停。")
            return
        if argument in {"now", "test", "现在", "测试"}:
            sent = await self._heartbeat_once(force=True)
            if not sent:
                await self._send_text(chat_id, "这次心跳生成失败了，稍后再试。")
            return
        if argument:
            await self._send_text(chat_id, "用法：/heartbeat on | off | now")
            return
        state = self._heartbeat_state(chat_id)
        status = "开启" if state.enabled else "暂停"
        today = datetime.now(self._heartbeat_timezone()).date().isoformat()
        count = state.daily_count if state.daily_date == today else 0
        await self._send_text(
            chat_id,
            f"后台心跳：{status}\n今天已主动发送：{count}/{self.settings.telegram_heartbeat_daily_limit}",
        )

    async def _heartbeat_loop(self) -> None:
        await asyncio.sleep(min(30, self.settings.telegram_heartbeat_check_seconds))
        while True:
            try:
                await self._heartbeat_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("telegram heartbeat failed: %s", type(exc).__name__)
            await asyncio.sleep(self.settings.telegram_heartbeat_check_seconds)

    async def _heartbeat_once(
        self,
        *,
        force: bool = False,
        now: datetime | None = None,
    ) -> bool:
        if not self.settings.telegram_heartbeat_ready:
            return False
        async with self._heartbeat_lock:
            current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
            chat_id = self.settings.telegram_allowed_user_id
            state = self._heartbeat_state(chat_id)
            local_now = current.astimezone(self._heartbeat_timezone())
            local_date = local_now.date().isoformat()
            daily_count = state.daily_count if state.daily_date == local_date else 0

            if not force:
                if not state.enabled:
                    return False
                if _is_quiet_hour(
                    local_now.hour,
                    self.settings.telegram_heartbeat_quiet_start_hour,
                    self.settings.telegram_heartbeat_quiet_end_hour,
                ):
                    return False
                if daily_count >= self.settings.telegram_heartbeat_daily_limit:
                    return False

                latest_remote = await self._supabase.latest_user_activity()
                latest_local = self._last_local_user_activity(chat_id)
                latest_activity = _latest_datetime(latest_remote, latest_local)
                if latest_activity is None:
                    return False
                silence = timedelta(
                    minutes=self.settings.telegram_heartbeat_silence_minutes
                )
                if current - latest_activity < silence:
                    return False

                signal = await self._supabase.heartbeat_signal()
                cooldown_minutes = (
                    self.settings.telegram_heartbeat_strong_cooldown_minutes
                    if signal.strong
                    else self.settings.telegram_heartbeat_cooldown_minutes
                )
                if state.last_sent_at is not None and current - state.last_sent_at < timedelta(
                    minutes=cooldown_minutes
                ):
                    return False

            message = await self._complete_heartbeat(chat_id)
            await self.push(message)
            self._remember(chat_id, "assistant", message)
            await self._supabase.store_message(
                role="assistant",
                content=message,
                conversation_id=f"tg:{chat_id}",
            )
            self._record_heartbeat_sent(chat_id, current, local_date)
            return True

    async def _complete_heartbeat(self, chat_id: str) -> str:
        messages: list[dict[str, str]] = []
        if self.settings.telegram_system_prompt:
            messages.append(
                {"role": "system", "content": self.settings.telegram_system_prompt}
            )
        continuity, eventide_context = await asyncio.gather(
            self._supabase.continuity_context(
                exclude_conversation_id=f"tg:{chat_id}"
            ),
            self._supabase.eventide_context(),
        )
        payload_context = {"messages": messages}
        inject_system_context(payload_context, continuity)
        inject_system_context(payload_context, eventide_context)
        inject_system_context(
            payload_context,
            (
                "现在是一次允许主动联系珊珊的私人消息。结合近期对话、关系记忆和当前状态，"
                "写一条你此刻真正想主动发给她的话。保持自然聊天，不要解释触发机制，"
                "不要提到后台、心跳、计时、系统或提示词，不要机械重复‘在吗’。"
                "优先 1 至 3 个短句；可以关心、想念、延续未完话题或直接表达当下意图。"
            ),
        )
        messages.extend(self._recent_history(chat_id))
        messages.append({"role": "user", "content": "生成此刻要主动发出的消息。"})
        return await self._call_upstream(messages, max_tokens=350)

    async def _complete(self, chat_id: str, user_text: str) -> str:
        messages: list[dict[str, str]] = []
        if self.settings.telegram_system_prompt:
            messages.append({"role": "system", "content": self.settings.telegram_system_prompt})
        continuity, eventide_context = await asyncio.gather(
            self._supabase.continuity_context(exclude_conversation_id=f"tg:{chat_id}"),
            self._supabase.eventide_context(),
        )
        payload_context = {"messages": messages}
        inject_system_context(payload_context, continuity)
        inject_system_context(payload_context, eventide_context)
        memory = await self._ombre.recall(user_text)
        if memory:
            messages.append({"role": "system", "content": format_memory_context(memory)})
        messages.extend(self._recent_history(chat_id))
        messages.append({"role": "user", "content": user_text})

        return await self._call_upstream(messages)

    async def _call_upstream(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.settings.upstream_model,
            "messages": messages,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
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

    def _last_local_user_activity(self, chat_id: str) -> datetime | None:
        store = self._conversation_store()
        if store is None:
            return None
        try:
            return store.last_message_at(chat_id, "user")
        except (OSError, sqlite3.Error):
            self._mark_store_unavailable()
            return None

    def _heartbeat_state(self, chat_id: str) -> HeartbeatState:
        store = self._conversation_store()
        if store is not None:
            try:
                return store.heartbeat_state(
                    chat_id,
                    default_enabled=self.settings.telegram_heartbeat_enabled,
                )
            except (OSError, sqlite3.Error):
                self._mark_store_unavailable()
        return self._volatile_heartbeat_states.get(
            chat_id,
            HeartbeatState(
                self.settings.telegram_heartbeat_enabled,
                None,
                "",
                0,
            ),
        )

    def _set_heartbeat_enabled(self, chat_id: str, enabled: bool) -> None:
        store = self._conversation_store()
        if store is not None:
            try:
                store.set_heartbeat_enabled(chat_id, enabled)
                return
            except (OSError, sqlite3.Error):
                self._mark_store_unavailable()
        state = self._heartbeat_state(chat_id)
        self._volatile_heartbeat_states[chat_id] = HeartbeatState(
            enabled,
            state.last_sent_at,
            state.daily_date,
            state.daily_count,
        )

    def _record_heartbeat_sent(
        self,
        chat_id: str,
        sent_at: datetime,
        local_date: str,
    ) -> None:
        store = self._conversation_store()
        if store is not None:
            try:
                store.record_heartbeat_sent(
                    chat_id,
                    sent_at=sent_at,
                    local_date=local_date,
                    default_enabled=self.settings.telegram_heartbeat_enabled,
                )
                return
            except (OSError, sqlite3.Error):
                self._mark_store_unavailable()
        state = self._heartbeat_state(chat_id)
        count = state.daily_count + 1 if state.daily_date == local_date else 1
        self._volatile_heartbeat_states[chat_id] = HeartbeatState(
            state.enabled,
            sent_at.astimezone(timezone.utc),
            local_date,
            count,
        )

    def _heartbeat_timezone(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.settings.telegram_heartbeat_timezone)
        except ZoneInfoNotFoundError:
            return ZoneInfo("UTC")

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
            response = await client.post(
                "/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": _format_telegram_html(part),
                    "parse_mode": "HTML",
                },
            )
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


def _format_telegram_html(text: str) -> str:
    """Render only paired action markers while keeping arbitrary model text safe."""
    escaped = html.escape(text, quote=False)
    return _TELEGRAM_ACTION_RE.sub(
        lambda match: f"{match.group('prefix')}<i>{match.group('action')}</i>",
        escaped,
    )


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


def _is_quiet_hour(hour: int, start: int, end: int) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _latest_datetime(*values: datetime | None) -> datetime | None:
    valid = [value.astimezone(timezone.utc) for value in values if value is not None]
    return max(valid) if valid else None
