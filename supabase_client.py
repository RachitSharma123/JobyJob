#!/usr/bin/env python3
"""
db/supabase_client.py
Shared Supabase client + job upsert/update helpers for the consulting applier.
Reads credentials from ~/.openclaw/.env (same as existing system).
"""

import os
import json
from pathlib import Path
from datetime import date, datetime
from typing import Optional

import httpx


def _load_env():
    env_file = Path.home() / ".openclaw" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

SUPABASE_URL = os.getenv("SUPABASE_URL", "https://nymazemxiqetxxwcwgew.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "sb_secret_RHU8o4kvpazyTBjlcALvPw_PQ1d0yME")

_HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _req(method: str, path: str, **kwargs) -> httpx.Response:
    url = f"{SUPABASE_URL}{path}"
    resp = httpx.request(method, url, headers=_HEADERS, timeout=20, **kwargs)
    return resp


# ── Schema migration ──────────────────────────────────────────────────────────

MIGRATION_SQL = """
ALTER TABLE job_applications
  ADD COLUMN IF NOT EXISTS firm_name TEXT,
  ADD COLUMN IF NOT EXISTS ats_type TEXT,
  ADD COLUMN IF NOT EXISTS ats_job_id TEXT,
  ADD COLUMN IF NOT EXISTS ats_company_id TEXT,
  ADD COLUMN IF NOT EXISTS ats_board_token TEXT,
  ADD COLUMN IF NOT EXISTS department TEXT,
  ADD COLUMN IF NOT EXISTS application_screenshot_path TEXT,
  ADD COLUMN IF NOT EXISTS telegram_message_id BIGINT,
  ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS applied_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS follow_up_sent BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS error_log TEXT,
  ADD COLUMN IF NOT EXISTS job_url TEXT;

CREATE INDEX IF NOT EXISTS idx_job_applications_firm_name ON job_applications(firm_name);
CREATE INDEX IF NOT EXISTS idx_job_applications_ats_type ON job_applications(ats_type);
CREATE INDEX IF NOT EXISTS idx_job_applications_applied_at ON job_applications(applied_at);
"""


def run_migration():
    """Add new columns to existing job_applications table."""
    resp = _req("POST", "/rest/v1/rpc/exec_sql", json={"query": MIGRATION_SQL})
    if resp.status_code in [200, 201]:
        print("Migration applied successfully")
    else:
        print(f"Migration response: {resp.status_code} — {resp.text}")


# ── Job operations ────────────────────────────────────────────────────────────

def job_exists(external_id: str) -> bool:
    """Check if a job already exists by external_id."""
    resp = _req(
        "GET",
        f"/rest/v1/job_applications?external_id=eq.{external_id}&select=id&limit=1",
    )
    if resp.status_code == 200:
        return len(resp.json()) > 0
    return False


def get_existing_external_ids() -> set[str]:
    """Fetch all external_ids from Supabase (for bulk dedup)."""
    resp = _req("GET", "/rest/v1/job_applications?select=external_id&limit=5000")
    if resp.status_code == 200:
        return {row["external_id"] for row in resp.json() if row.get("external_id")}
    return set()


def upsert_job(job: dict) -> Optional[str]:
    """
    Insert a new job. Returns UUID if created, None if duplicate/error.
    Maps our normalized job dict to job_applications schema.
    """
    payload = {
        "external_id": job.get("external_id"),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "apply_url": job.get("apply_url"),
        "job_url": job.get("job_url"),
        "source": job.get("source", "consulting_applier"),
        "ats_type": job.get("ats_type"),
        "firm_name": job.get("firm_name"),
        "ats_job_id": job.get("ats_job_id"),
        "ats_company_id": job.get("ats_company_id"),
        "ats_board_token": job.get("ats_board_token"),
        "department": job.get("department"),
        "description": job.get("description", ""),
        "date_found": job.get("date_found", str(date.today())),
        "status": "new",
    }
    # Remove None values
    payload = {k: v for k, v in payload.items() if v is not None}

    resp = _req(
        "POST",
        "/rest/v1/job_applications",
        json=payload,
        headers={**_HEADERS, "Prefer": "return=representation,resolution=ignore-duplicates"},
    )
    if resp.status_code in [200, 201]:
        rows = resp.json()
        if rows:
            return rows[0].get("id")
    elif resp.status_code == 409:
        pass  # duplicate, expected
    else:
        print(f"  [db] upsert failed for {job.get('title')}: {resp.status_code} {resp.text[:200]}")
    return None


def update_job_status(
    external_id: str,
    status: str,
    telegram_message_id: int = None,
    approved_at: str = None,
    applied_at: str = None,
    screenshot_path: str = None,
    error_log: str = None,
):
    """Update job status and optional fields."""
    payload = {"status": status}
    if telegram_message_id:
        payload["telegram_message_id"] = telegram_message_id
    if approved_at:
        payload["approved_at"] = approved_at
    if applied_at:
        payload["applied_at"] = applied_at
    if screenshot_path:
        payload["application_screenshot_path"] = screenshot_path
    if error_log:
        payload["error_log"] = error_log
    payload["updated_at"] = datetime.utcnow().isoformat()

    resp = _req(
        "PATCH",
        f"/rest/v1/job_applications?external_id=eq.{external_id}",
        json=payload,
    )
    return resp.status_code in [200, 204]


def get_pending_approvals() -> list[dict]:
    """Get jobs waiting for Telegram approval (status=new, telegram_message_id set)."""
    resp = _req(
        "GET",
        "/rest/v1/job_applications?status=eq.new&telegram_message_id=not.is.null&select=*&order=date_found.desc&limit=20",
    )
    if resp.status_code == 200:
        return resp.json()
    return []


def get_todays_applications() -> list[dict]:
    """Get jobs applied today."""
    today = str(date.today())
    resp = _req(
        "GET",
        f"/rest/v1/job_applications?status=eq.applied&applied_at=gte.{today}T00:00:00&select=title,company,applied_at&order=applied_at.desc",
    )
    if resp.status_code == 200:
        return resp.json()
    return []


if __name__ == "__main__":
    print("Running schema migration...")
    run_migration()
    print("\nTesting connection...")
    ids = get_existing_external_ids()
    print(f"Existing jobs in DB: {len(ids)}")
