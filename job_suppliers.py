#!/usr/bin/env python3
"""Aggregated job supplier fetchers: Adzuna, Careerjet, Seek, and JSearch."""

from __future__ import annotations

import os
from typing import Any

import requests


def _safe_get(url: str, *, params: dict | None = None, headers: dict | None = None) -> dict:
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=25)
        if resp.status_code == 200:
            return resp.json()
        return {"_error": f"{resp.status_code} {resp.text[:240]}"}
    except Exception as exc:
        return {"_error": str(exc)}


def fetchadzuna(what: str, where: str = "Melbourne", page: int = 1) -> list[dict[str, Any]]:
    app_id = os.getenv("ADZUNA_APP_ID", "c30cd290")
    app_key = os.getenv("ADZUNA_APP_KEY", "b32022fa399145cc74d2632e9077e257")
    data = _safe_get(
        f"https://api.adzuna.com/v1/api/jobs/au/search/{page}",
        params={"app_id": app_id, "app_key": app_key, "what": what, "where": where, "results_per_page": 50},
    )
    results = []
    for row in data.get("results", []):
        results.append(
            {
                "source": "adzuna",
                "ats_type": "adzuna",
                "external_id": f"adzuna_{row.get('id')}",
                "title": row.get("title", ""),
                "company": (row.get("company") or {}).get("display_name", ""),
                "firm_name": (row.get("company") or {}).get("display_name", ""),
                "location": (row.get("location") or {}).get("display_name", ""),
                "description": row.get("description", ""),
                "apply_url": row.get("redirect_url", ""),
                "salary_min": row.get("salary_min"),
                "salary_max": row.get("salary_max"),
                "raw": row,
            }
        )
    return results


def fetchcareerjet(what: str, where: str = "Melbourne", page: int = 1) -> list[dict[str, Any]]:
    affiliate = os.getenv("CAREERJET_AFFID", "2afd67899eb64e531f270447ff3d7995")
    data = _safe_get(
        "https://public.api.careerjet.net/search",
        params={"locale_code": "en_AU", "affid": affiliate, "keywords": what, "location": where, "page": page},
    )
    results = []
    for row in data.get("jobs", []):
        results.append(
            {
                "source": "careerjet",
                "ats_type": "careerjet",
                "external_id": f"careerjet_{row.get('url')}",
                "title": row.get("title", ""),
                "company": row.get("company", ""),
                "firm_name": row.get("company", ""),
                "location": row.get("locations", ""),
                "description": row.get("description", ""),
                "apply_url": row.get("url", ""),
                "salary_min": None,
                "salary_max": None,
                "raw": row,
            }
        )
    return results


def fetchseek(what: str, where: str = "Melbourne") -> list[dict[str, Any]]:
    data = _safe_get(
        "https://www.seek.com.au/api/jobsearch/v5/search",
        params={"keywords": what, "where": where, "page": 1},
    )
    results = []
    for row in data.get("data", []):
        listing = row.get("listing", {})
        results.append(
            {
                "source": "seek",
                "ats_type": "seek",
                "external_id": f"seek_{listing.get('id')}",
                "title": listing.get("title", ""),
                "company": (listing.get("advertiser") or {}).get("description", ""),
                "firm_name": (listing.get("advertiser") or {}).get("description", ""),
                "location": (listing.get("locations") or [{}])[0].get("label", ""),
                "description": listing.get("teaser", ""),
                "apply_url": listing.get("jobUrl", ""),
                "salary_min": None,
                "salary_max": None,
                "raw": row,
            }
        )
    return results


def fetchjsearch(what: str, where: str = "Melbourne") -> list[dict[str, Any]]:
    api_key = os.getenv("RAPIDAPI_KEY", "")
    data = _safe_get(
        "https://jsearch.p.rapidapi.com/search",
        params={"query": f"{what} in {where}", "page": "1", "num_pages": "1", "country": "au"},
        headers={"X-RapidAPI-Key": api_key, "X-RapidAPI-Host": "jsearch.p.rapidapi.com"} if api_key else None,
    )
    results = []
    for row in data.get("data", []):
        results.append(
            {
                "source": "jsearch",
                "ats_type": "jsearch",
                "external_id": f"jsearch_{row.get('job_id')}",
                "title": row.get("job_title", ""),
                "company": row.get("employer_name", ""),
                "firm_name": row.get("employer_name", ""),
                "location": row.get("job_city") or row.get("job_country", ""),
                "description": row.get("job_description", ""),
                "apply_url": row.get("job_apply_link", ""),
                "salary_min": row.get("job_min_salary"),
                "salary_max": row.get("job_max_salary"),
                "raw": row,
            }
        )
    return results


def run_supplier_search(what: str, where: str, suppliers: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if "adzuna" in suppliers:
        out.extend(fetchadzuna(what=what, where=where))
    if "careerjet" in suppliers:
        out.extend(fetchcareerjet(what=what, where=where))
    if "seek" in suppliers:
        out.extend(fetchseek(what=what, where=where))
    if "jsearch" in suppliers:
        out.extend(fetchjsearch(what=what, where=where))
    return out


def post_to_jobprocessor(jobs: list[dict[str, Any]], endpoint: str = "http://localhost:5680") -> dict[str, Any]:
    try:
        resp = requests.post(endpoint, json={"jobs": jobs}, timeout=30)
        return {"ok": resp.ok, "status_code": resp.status_code, "text": resp.text[:500]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}



def _to_supabase_payload(job: dict[str, Any]) -> dict[str, Any]:
    """Map supplier job shape to the existing Supabase job schema."""
    return {
        "external_id": job.get("external_id"),
        "title": job.get("title", ""),
        "company": job.get("company", ""),
        "location": job.get("location", ""),
        "description": job.get("description", ""),
        "apply_url": job.get("apply_url", ""),
        "job_url": job.get("apply_url", ""),
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "source": job.get("source", "supplier"),
        "ats_type": f"supplier_{job.get('source', 'unknown')}",
        "firm_name": job.get("company", ""),
    }


def save_jobs_to_supabase(jobs: list[dict[str, Any]]) -> dict[str, int]:
    """Upsert supplier jobs into Supabase using the project's existing db client."""
    try:
        from db.supabase_client import upsert_job
    except ModuleNotFoundError:
        from supabase_client import upsert_job

    inserted = 0
    skipped = 0

    for job in jobs:
        payload = _to_supabase_payload(job)
        uid = upsert_job(payload)
        if uid:
            inserted += 1
        else:
            skipped += 1

    return {"inserted": inserted, "skipped": skipped, "total": len(jobs)}
