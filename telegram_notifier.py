#!/usr/bin/env python3
"""
bot/telegram_notifier.py
Sends job cards to Telegram with inline keyboard (Apply / Skip / Open).
Uses raw HTTP (requests) — no python-telegram-bot dependency needed yet.

Callback data format: "approve:{external_id}" or "skip:{external_id}"
The callback handler (bot_server.py, built next) reads these.
"""

import os
import json
import requests
from pathlib import Path


def _load_env():
    env_file = Path.home() / ".openclaw" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8678095493:AAHMWIB5x_YQdwECdOaCqRzEZ3hg1T9GMn4")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8280691508")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


def _post(endpoint: str, payload: dict) -> dict:
    resp = requests.post(f"{API_BASE}/{endpoint}", json=payload, timeout=15)
    return resp.json()


def _format_salary(job: dict) -> str:
    lo = job.get("salary_min")
    hi = job.get("salary_max")
    if lo and hi:
        return f"${lo:,} – ${hi:,} AUD"
    elif lo:
        return f"${lo:,}+ AUD"
    return "Not specified"


def _format_card(job: dict) -> str:
    """Format job as Telegram markdown message."""
    title = job.get("title", "")
    company = job.get("firm_name") or job.get("company", "")
    location = job.get("location", "Melbourne, VIC")
    ats = job.get("ats_type", "").upper()
    salary = _format_salary(job)
    dept = job.get("department", "")
    desc = (job.get("description", "") or "")[:300].strip()
    if desc:
        desc = desc.replace("\n", " ")
        desc = f'\n\n_{desc}..._' if len(desc) >= 290 else f'\n\n_{desc}_'

    dept_line = f"\n*Dept:* {dept}" if dept else ""

    return (
        f"*{title}*\n"
        f"*{company}* `[{ats}]`\n"
        f"*Location:* {location}\n"
        f"*Salary:* {salary}"
        f"{dept_line}"
        f"{desc}"
    )


def send_job_card(job: dict) -> int | None:
    """
    Send a job card with inline keyboard buttons.
    Returns message_id if sent, None on failure.
    """
    ext_id = job.get("external_id", "")
    apply_url = job.get("apply_url", "")
    text = _format_card(job)

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Apply", "callback_data": f"approve:{ext_id}"},
                {"text": "Skip", "callback_data": f"skip:{ext_id}"},
            ],
            [
                {"text": "Open job", "url": apply_url},
            ],
        ]
    }

    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": keyboard,
        "disable_web_page_preview": True,
    }

    result = _post("sendMessage", payload)
    if result.get("ok"):
        return result["result"]["message_id"]
    else:
        print(f"  [telegram] sendMessage failed: {result.get('description')}")
        return None


def send_text(text: str, parse_mode: str = "Markdown") -> bool:
    """Send a plain text message."""
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    result = _post("sendMessage", payload)
    return result.get("ok", False)


def edit_card_after_action(message_id: int, action: str, job_title: str) -> bool:
    """
    Update card text after user taps Apply or Skip.
    Removes the inline keyboard so it can't be double-tapped.
    """
    icons = {"approve": "✅ Applying...", "skip": "❌ Skipped", "applied": "✅ Applied!"}
    label = icons.get(action, action)
    new_text = f"{label}\n*{job_title}*"

    payload = {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": []},
    }
    result = _post("editMessageText", payload)
    return result.get("ok", False)


if __name__ == "__main__":
    # Test with a dummy job
    test_job = {
        "external_id": "test_lever_abc123",
        "title": "Senior Data Analyst",
        "firm_name": "Thoughtworks Australia",
        "company": "Thoughtworks",
        "location": "Melbourne, VIC",
        "ats_type": "lever",
        "salary_min": 110000,
        "salary_max": 130000,
        "apply_url": "https://jobs.lever.co/thoughtworks/test",
        "description": "We are looking for a Senior Data Analyst to join our Melbourne team. You will work with clients across financial services, retail, and government sectors.",
    }
    msg_id = send_job_card(test_job)
    if msg_id:
        print(f"Card sent! message_id: {msg_id}")
    else:
        print("Failed to send card")
