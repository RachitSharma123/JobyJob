#!/usr/bin/env python3
"""
orchestrator/daily_runner.py
Main cron entry point for the consulting applier pipeline.

What it does:
  1. Runs all ATS scrapers (Lever, Workday, Greenhouse)
  2. Filters out jobs already in Supabase
  3. Upserts new jobs to Supabase
  4. Sends Telegram notification cards for each new job (with approve/skip buttons)

Cron (add to crontab on VPS):
  0 6 * * * cd /home/rachit/.openclaw/workspace/consulting_applier && python3 orchestrator/daily_runner.py >> logs/runner.log 2>&1

Usage:
  python3 orchestrator/daily_runner.py
  python3 orchestrator/daily_runner.py --ats lever          # only Lever firms
  python3 orchestrator/daily_runner.py --dry-run            # scrape only, no DB/Telegram
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "firms.json").exists() else HERE.parent
sys.path.insert(0, str(ROOT))

try:
    from scraper.scraper_router import run_all_scrapers
    from db.supabase_client import get_existing_external_ids, upsert_job
    from bot.telegram_notifier import send_job_card
except ModuleNotFoundError:
    # Flat-repo fallback (used by Streamlit Cloud in this repository layout)
    from scraper_router import run_all_scrapers
    from supabase_client import get_existing_external_ids, upsert_job
    from telegram_notifier import send_job_card


def _log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run_pipeline(
    ats_filter: list[str] = None,
    dry_run: bool = False,
    max_notify: int = 15,
):
    _log("=== Consulting Applier — Daily Runner ===")
    _log(f"ATS filter: {ats_filter or 'all'} | dry_run: {dry_run}")

    # Step 1: Scrape all firms
    _log("Step 1: Scraping all firms...")
    jobs = run_all_scrapers(ats_filter=ats_filter)
    _log(f"Scraped {len(jobs)} jobs total")

    if not jobs:
        _log("No jobs found. Exiting.")
        return

    if dry_run:
        _log("[DRY RUN] Skipping DB and Telegram. Jobs found:")
        for j in jobs[:20]:
            sal = f" | ${j['salary_min']:,}" if j.get("salary_min") else ""
            _log(f"  [{j['ats_type']}] {j['company']} — {j['title']}{sal}")
        _log(f"\nTotal: {len(jobs)} jobs")
        return

    # Step 2: Filter out existing jobs
    _log("Step 2: Checking Supabase for duplicates...")
    existing_ids = get_existing_external_ids()
    new_jobs = [j for j in jobs if j.get("external_id") not in existing_ids]
    _log(f"{len(jobs) - len(new_jobs)} already in DB → {len(new_jobs)} new jobs to process")

    if not new_jobs:
        _log("No new jobs today. Done.")
        return

    # Step 3: Upsert to Supabase
    _log("Step 3: Storing new jobs in Supabase...")
    stored = 0
    for job in new_jobs:
        uid = upsert_job(job)
        if uid:
            stored += 1
    _log(f"Stored {stored}/{len(new_jobs)} new jobs")

    # Step 4: Send Telegram cards (cap at max_notify per run)
    notify_jobs = new_jobs[:max_notify]
    _log(f"Step 4: Sending {len(notify_jobs)} Telegram notifications...")

    sent = 0
    failed = 0
    for job in notify_jobs:
        try:
            msg_id = send_job_card(job)
            if msg_id:
                # Update telegram_message_id in DB
                try:
                    from db.supabase_client import update_job_status
                except ModuleNotFoundError:
                    from supabase_client import update_job_status
                update_job_status(
                    job["external_id"],
                    status="new",
                    telegram_message_id=msg_id,
                )
                sent += 1
            else:
                failed += 1
        except Exception as e:
            _log(f"  Telegram failed for {job['title']}: {e}")
            failed += 1

    _log(f"Telegram: {sent} sent, {failed} failed")

    # Step 5: Summary message
    summary_lines = [
        f"*Daily Scrape Summary — {datetime.now().strftime('%d %b %Y')}*",
        f"",
        f"Firms scraped: all active",
        f"Total jobs found: {len(jobs)}",
        f"New jobs: {len(new_jobs)}",
        f"Notifications sent: {sent}",
        f"",
        f"Review cards above and tap *Apply* to approve.",
    ]

    try:
        try:
            from bot.telegram_notifier import send_text
        except ModuleNotFoundError:
            from telegram_notifier import send_text
        send_text("\n".join(summary_lines))
    except Exception as e:
        _log(f"Summary message failed: {e}")

    _log("=== Done ===")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ats", nargs="+", help="Filter ATS: lever workday greenhouse")
    parser.add_argument("--dry-run", action="store_true", help="Scrape only, no DB/Telegram")
    parser.add_argument("--max-notify", type=int, default=15, help="Max Telegram cards per run")
    args = parser.parse_args()

    run_pipeline(
        ats_filter=args.ats,
        dry_run=args.dry_run,
        max_notify=args.max_notify,
    )
