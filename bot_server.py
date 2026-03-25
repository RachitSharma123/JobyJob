#!/usr/bin/env python3
"""
bot/bot_server.py
FastAPI webhook server — handles Telegram inline button callbacks.

Approve -> edits card -> triggers Playwright applier in background
Skip    -> edits card -> marks skipped in DB

Run on VPS:
  uvicorn bot.bot_server:app --host 0.0.0.0 --port 8765 --reload

Set webhook once:
  python3 bot/bot_server.py --set-webhook https://YOUR_VPS_IP:8765/webhook

Bot commands handled:
  /status   — pipeline health
  /queue    — pending approvals
  /applied  — today's applications
  /pause    — pause automation
  /resume   — resume automation
"""

import os
import sys
import json
import asyncio
import argparse
import requests
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import JSONResponse

from db.supabase_client import update_job_status, get_pending_approvals, get_todays_applications, _req as db_req
from bot.telegram_notifier import edit_card_after_action, send_text, BOT_TOKEN, CHAT_ID, API_BASE

app = FastAPI(title="Consulting Applier Bot")

# Simple pause flag (in-memory, resets on restart)
_PAUSED = False


# ── Telegram helpers ──────────────────────────────────────────────────────────

def answer_callback(callback_query_id: str, text: str = ""):
    requests.post(
        f"{API_BASE}/answerCallbackQuery",
        json={"callback_query_id": callback_query_id, "text": text},
        timeout=5,
    )


def set_webhook(url: str):
    resp = requests.post(
        f"{API_BASE}/setWebhook",
        json={"url": url, "allowed_updates": ["callback_query", "message"]},
        timeout=10,
    )
    data = resp.json()
    print(f"Webhook {'set OK' if data.get('ok') else 'FAILED'}: {data}")


def delete_webhook():
    resp = requests.post(f"{API_BASE}/deleteWebhook", timeout=10)
    print(resp.json())


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_job(external_id: str) -> Optional[dict]:
    resp = db_req("GET", f"/rest/v1/job_applications?external_id=eq.{external_id}&select=*&limit=1")
    if resp.status_code == 200:
        rows = resp.json()
        return rows[0] if rows else None
    return None


# ── Applier trigger ───────────────────────────────────────────────────────────

async def trigger_apply(external_id: str, job: dict):
    """Background task: run Playwright applier, update DB and Telegram when done."""
    ats = job.get("ats_type", "")
    title = job.get("title", "")
    company = job.get("company", "")
    message_id = job.get("telegram_message_id")

    # Mark approved immediately
    update_job_status(
        external_id,
        status="approved",
        approved_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        loop = asyncio.get_event_loop()

        if ats == "lever":
            from applier.apply_lever import apply_lever
            result = await loop.run_in_executor(None, apply_lever, job)
        elif ats == "greenhouse":
            from applier.apply_greenhouse import apply_greenhouse
            result = await loop.run_in_executor(None, apply_greenhouse, job)
        elif ats == "workday":
            from applier.apply_workday import apply_workday
            result = await loop.run_in_executor(None, apply_workday, job)
        else:
            result = {"success": False, "error": f"No applier built yet for: {ats}"}

        if result.get("success"):
            update_job_status(
                external_id,
                status="applied",
                applied_at=datetime.now(timezone.utc).isoformat(),
                screenshot_path=result.get("screenshot_path"),
            )
            if message_id:
                edit_card_after_action(message_id, "applied", title)
            send_text(f"Applied to *{title}* at *{company}*")
        else:
            err = result.get("error", "Unknown error")
            update_job_status(external_id, status="error", error_log=err[:500])
            if message_id:
                edit_card_after_action(message_id, "error", title)
            send_text(f"Apply failed: *{title}*\n`{err[:200]}`")

    except Exception as e:
        err = str(e)
        update_job_status(external_id, status="error", error_log=err[:500])
        if message_id:
            edit_card_after_action(message_id, "error", title)
        send_text(f"Apply crashed: *{title}*\n`{err[:200]}`")


# ── Command handler ───────────────────────────────────────────────────────────

def handle_command(text: str):
    global _PAUSED
    cmd = text.strip().split()[0].lower()

    if cmd == "/status":
        pending = get_pending_approvals()
        applied = get_todays_applications()
        msg = (
            f"*Pipeline Status*\n"
            f"State: {'PAUSED' if _PAUSED else 'Running'}\n"
            f"Pending approvals: {len(pending)}\n"
            f"Applied today: {len(applied)}"
        )
        send_text(msg)

    elif cmd == "/queue":
        jobs = get_pending_approvals()
        if not jobs:
            send_text("No jobs pending approval.")
            return
        lines = ["*Pending Approvals*\n"]
        for j in jobs[:10]:
            lines.append(f"• {j['title']} — {j['company']}")
        send_text("\n".join(lines))

    elif cmd == "/applied":
        jobs = get_todays_applications()
        if not jobs:
            send_text("No applications today yet.")
            return
        lines = ["*Applied Today*\n"]
        for j in jobs:
            t = j.get("applied_at", "")[:16].replace("T", " ")
            lines.append(f"• {j['title']} — {j['company']} `{t}`")
        send_text("\n".join(lines))

    elif cmd == "/pause":
        _PAUSED = True
        send_text("Automation paused. Send /resume to restart.")

    elif cmd == "/resume":
        _PAUSED = False
        send_text("Automation resumed.")

    elif cmd == "/help":
        send_text(
            "*Commands*\n"
            "/status — pipeline health\n"
            "/queue — pending approvals\n"
            "/applied — today's applications\n"
            "/pause — pause automation\n"
            "/resume — resume automation"
        )


# ── Webhook endpoint ──────────────────────────────────────────────────────────

@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Handle inline button callbacks
    if "callback_query" in update:
        cb = update["callback_query"]
        query_id = cb.get("id")
        data = cb.get("data", "")
        message = cb.get("message", {})
        message_id = message.get("message_id")

        parts = data.split(":", 1)
        action = parts[0] if parts else ""
        external_id = parts[1] if len(parts) > 1 else ""

        if action == "approve":
            if _PAUSED:
                answer_callback(query_id, "Bot is paused. Send /resume first.")
                return JSONResponse({"ok": True})

            answer_callback(query_id, "Queued for applying...")
            job = get_job(external_id)
            if not job:
                send_text(f"Job not found in DB: `{external_id}`")
                return JSONResponse({"ok": True})

            # Edit card immediately to show pending state
            if message_id:
                edit_card_after_action(message_id, "approve", job.get("title", ""))

            background_tasks.add_task(trigger_apply, external_id, job)

        elif action == "skip":
            answer_callback(query_id, "Skipped")
            update_job_status(external_id, status="skipped")
            if message_id:
                job = get_job(external_id)
                title = job.get("title", "") if job else external_id
                edit_card_after_action(message_id, "skip", title)

        else:
            answer_callback(query_id)

    # Handle text commands
    elif "message" in update:
        msg = update["message"]
        text = msg.get("text", "")
        chat_id = str(msg.get("chat", {}).get("id", ""))

        # Only respond to our own chat
        if chat_id == str(CHAT_ID) and text.startswith("/"):
            handle_command(text)

    return JSONResponse({"ok": True})


@app.get("/health")
async def health():
    return {"status": "ok", "paused": _PAUSED, "timestamp": datetime.utcnow().isoformat()}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--set-webhook", metavar="URL", help="Set Telegram webhook URL")
    parser.add_argument("--delete-webhook", action="store_true")
    parser.add_argument("--serve", action="store_true", help="Run server directly (uses uvicorn)")
    args = parser.parse_args()

    if args.set_webhook:
        set_webhook(args.set_webhook)
    elif args.delete_webhook:
        delete_webhook()
    elif args.serve:
        import uvicorn
        uvicorn.run("bot.bot_server:app", host="0.0.0.0", port=8765, reload=False)
    else:
        parser.print_help()
