"""Private-chat delivery with bounded messages and a resumable journal."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from .core import UTC, digest, iso, timestamp
from .report import render


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def split_messages(sections: list[str], limit: int = 3500) -> list[str]:
    chunks, current = [], ""
    for section in sections:
        for line in section.splitlines():
            # Hard split long URLs/text without dropping any content or splitting a surrogate pair.
            while units(line) > limit:
                cut = min(len(line), limit)
                while units(line[:cut]) > limit:
                    cut -= 1
                if current:
                    chunks.append(current.rstrip())
                    current = ""
                chunks.append(line[:cut])
                line = line[cut:]
            if units(current + line + "\n") > limit and current:
                chunks.append(current.rstrip())
                current = ""
            current += line + "\n"
        current += "\n"
    if current.strip():
        chunks.append(current.rstrip())
    return [f"[{i}/{len(chunks)}]\n{chunk}" for i, chunk in enumerate(chunks, 1)]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("Telegram redirects are not permitted")


def rejection_hint(data: object) -> str:
    # Only emit fixed guidance; Telegram error bodies can contain private inputs.
    if not isinstance(data, dict):
        return "credentials omitted"
    hints = {
        "Forbidden: bot was blocked by the user": "Unblock the bot and press Start in your private chat",
        "Forbidden: bot can't initiate conversation with a user": "Open your bot and press Start before retrying",
        "Forbidden: bot can't send messages to bots": "TELEGRAM_CHAT_ID must be your message.chat.id from getUpdates, not a bot ID",
        "Forbidden: user is deactivated": "TELEGRAM_CHAT_ID belongs to a deactivated account",
        "Bad Request: chat not found": "Start the bot, then set TELEGRAM_CHAT_ID to your message.chat.id from getUpdates",
        "Unauthorized": "Check TELEGRAM_BOT_TOKEN in this repository's Actions secrets",
    }
    description = data.get("description")
    return hints.get(description, "credentials omitted") if isinstance(description, str) else "credentials omitted"


class Telegram:
    def __init__(self, token: str, chat_id: str):
        if not re.fullmatch(r"\d+:[A-Za-z0-9_-]+", token or ""):
            raise ValueError("TELEGRAM_BOT_TOKEN is missing or malformed")
        if not re.fullmatch(r"[1-9]\d{0,15}", chat_id or ""):
            raise ValueError("TELEGRAM_CHAT_ID must be the configured positive private-chat ID")
        self.token, self.chat_id = token, chat_id

    def call(self, method, payload):
        request = Request(f"https://api.telegram.org/bot{self.token}/{method}",
                          data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with build_opener(NoRedirect()).open(request, timeout=30) as response:
                data = json.load(response)
        except HTTPError as exc:
            try:
                error = json.loads(exc.read(4096))
            except Exception:
                error = None
            raise RuntimeError(f"Telegram rejected {method} (HTTP {exc.code}); {rejection_hint(error)}") from None
        except Exception:
            # A timeout may follow acceptance by Telegram. Never blindly retry a send.
            raise RuntimeError(f"Telegram {method} outcome uncertain; check the chat before retrying") from None
        if not data.get("ok"):
            raise RuntimeError(f"Telegram rejected {method}; {rejection_hint(data)}")
        return data["result"]

    def verify(self):
        bot = self.call("getMe", {})
        if str(bot.get("id")) == self.chat_id:
            raise ValueError("TELEGRAM_CHAT_ID points to this bot. Start the bot, then use your message.chat.id from getUpdates; getMe returns the bot's ID.")
        data = self.call("getChat", {"chat_id": self.chat_id})
        if data.get("type") != "private" or str(data.get("id")) != self.chat_id:
            raise ValueError("Configured destination did not verify as the expected private chat")


def deliver(report: dict, state_path: Path, telegram: Telegram, now: datetime | None = None):
    now = now or datetime.now(UTC)
    generated = timestamp(report.get("generated_at", ""))
    date = now.astimezone(ZoneInfo(report["timezone"])).date().isoformat()
    if report.get("smoke") or report.get("synthetic"):
        raise ValueError("Smoke/synthetic reports are not eligible for scheduled delivery")
    if generated is None or not timedelta(0) <= now - generated <= timedelta(hours=6) or report["date"] != date:
        raise ValueError("Refusing a stale, future-dated or wrong-day report")
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    messages = split_messages(render(report))
    fingerprint = digest(json.dumps(messages, ensure_ascii=False))
    delivery = state.setdefault("delivery", {}).setdefault(date, {"cursor": 0, "fingerprint": fingerprint})
    if delivery["fingerprint"] != fingerprint:
        raise ValueError("This day's delivery already refers to a different report")
    if delivery.get("uncertain"):
        raise RuntimeError("Previous Telegram send has an uncertain outcome; review it before resetting the journal")
    if delivery.get("complete"):
        return 0
    telegram.verify()
    sent = 0
    for index in range(delivery["cursor"], len(messages)):
        delivery["uncertain"] = True
        atomic_json(state_path, state)
        result = telegram.call("sendMessage", {"chat_id": telegram.chat_id, "text": messages[index],
                                                 "link_preview_options": {"is_disabled": True}})
        chat = result.get("chat", {})
        if (not isinstance(result.get("message_id"), int) or
                str(chat.get("id")) != telegram.chat_id or chat.get("type") != "private"):
            raise RuntimeError("Telegram response did not confirm delivery to the expected private chat")
        delivery.update(cursor=index + 1, uncertain=False, last_message_id=result["message_id"])
        atomic_json(state_path, state)
        sent += 1
        time.sleep(1.1)
    delivery.update(complete=True, completed_at=iso(now))
    atomic_json(state_path, state)
    return sent
