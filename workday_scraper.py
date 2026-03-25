#!/usr/bin/env python3
"""
workday_scraper.py
Fetches job postings from Workday's public CXS (Candidate Experience) API.
No auth required — endpoint pattern:
  https://{tenant}.wd{N}.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs

POST with JSON body to filter. Returns paginated results.
"""

import httpx
import re
import json
from typing import Optional


# Common Workday subdomain numbers to try if primary fails
_WD_NUMS = ["1", "3", "5"]


def _parse_salary_from_text(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    patterns = [
        r"\$(\d{2,3})[Kk][\s\-–]+\$?(\d{2,3})[Kk]",
        r"\$(\d{2,3}),000[\s\-–]+\$?(\d{2,3}),000",
        r"(\d{2,3})[Kk][\s\-–]+(\d{2,3})[Kk]",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            lo = int(match.group(1).replace(",", ""))
            hi = int(match.group(2).replace(",", ""))
            lo = lo * 1000 if lo < 1000 else lo
            hi = hi * 1000 if hi < 1000 else hi
            return lo, hi
    return None, None


def _build_search_payload(location_filter: str, keywords: list[str], offset: int = 0) -> dict:
    """Build Workday CXS search payload."""
    search_text = " OR ".join(keywords) if keywords else ""
    return {
        "appliedFacets": {},
        "limit": 20,
        "offset": offset,
        "searchText": search_text,
    }


def _extract_job(item: dict, firm_name: str, ats_job_id: str, base_url: str) -> dict:
    """Normalize a Workday job item to our standard shape."""
    title = item.get("title", "")
    location_nodes = item.get("locationsText", "") or item.get("locations", [{}])
    if isinstance(location_nodes, list):
        location = ", ".join(
            loc.get("descriptor", "") for loc in location_nodes if loc.get("descriptor")
        )
    else:
        location = str(location_nodes)

    external_path = item.get("externalPath", "")
    apply_url = f"{base_url}{external_path}" if external_path else base_url

    description_raw = item.get("jobDescription", {})
    if isinstance(description_raw, dict):
        description = description_raw.get("descriptor", "")
    else:
        description = str(description_raw or "")

    posted_date = item.get("postedOn", "")

    salary_min, salary_max = _parse_salary_from_text(description)

    return {
        "external_id": f"workday_{ats_job_id}",
        "title": title,
        "company": firm_name,
        "location": location or "Melbourne, VIC",
        "salary_min": salary_min,
        "salary_max": salary_max,
        "apply_url": apply_url,
        "job_url": apply_url,
        "source": "workday",
        "ats_type": "workday",
        "firm_name": firm_name,
        "ats_job_id": ats_job_id,
        "description": description[:2000],
        "date_posted": posted_date,
    }


def scrape_workday(
    jobs_api: str,
    firm_name: str,
    location_filter: str = "Melbourne",
    role_keywords: list[str] = None,
    salary_min: int = 0,
    max_pages: int = 5,
) -> list[dict]:
    """
    Fetch and filter jobs from Workday CXS API.
    jobs_api example:
      https://deloitte.wd1.myworkdayjobs.com/wday/cxs/deloitte/DeloitteAUCareers/jobs
    """
    role_keywords = role_keywords or []
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/json",
    }

    # Derive base URL for apply links (strip /jobs suffix)
    base_url = jobs_api.replace("/wday/cxs/", "/").rsplit("/jobs", 1)[0]
    # Reconstruct proper apply base: https://{tenant}.wd*.myworkdayjobs.com/{board}/
    # Keep original API base for now
    apply_base = jobs_api.rsplit("/jobs", 1)[0].replace("/wday/cxs/", "/en-US/", 1)

    all_jobs = []
    seen_ids = set()
    offset = 0

    for page in range(max_pages):
        payload = _build_search_payload(location_filter, role_keywords, offset)
        try:
            resp = httpx.post(
                jobs_api,
                json=payload,
                headers=headers,
                timeout=25,
                follow_redirects=True,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            print(f"  [workday] {firm_name}: HTTP {e.response.status_code} on page {page}")
            break
        except Exception as e:
            print(f"  [workday] {firm_name}: {e}")
            break

        job_postings = data.get("jobPostings", [])
        total = data.get("total", 0)

        if not job_postings:
            break

        for item in job_postings:
            ats_id = item.get("bulletFields", [""])[0] if item.get("bulletFields") else ""
            if not ats_id:
                # Use externalPath as unique ID
                ats_id = item.get("externalPath", "").strip("/").replace("/", "_")
            if not ats_id:
                continue
            if ats_id in seen_ids:
                continue
            seen_ids.add(ats_id)

            title = item.get("title", "").lower()
            description_snippet = item.get("locationsText", "")

            # Keyword filter on title
            if role_keywords:
                if not any(kw.lower() in title for kw in role_keywords):
                    continue

            # Location filter
            location_text = (item.get("locationsText", "") or "").lower()
            if location_filter and location_filter.lower() not in location_text:
                if "remote" not in location_text and "australia" not in location_text:
                    continue

            job = _extract_job(item, firm_name, ats_id, apply_base)

            # Salary filter — only filter if we found a salary AND it's below threshold
            if salary_min and job["salary_min"] and job["salary_min"] < salary_min:
                continue

            all_jobs.append(job)

        offset += len(job_postings)
        if offset >= total:
            break

    print(f"  [workday] {firm_name}: {len(all_jobs)} matched jobs")
    return all_jobs


if __name__ == "__main__":
    # Quick test — Accenture
    results = scrape_workday(
        jobs_api="https://accenture.wd3.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs",
        firm_name="Accenture Australia",
        location_filter="Melbourne",
        role_keywords=["technology", "consulting", "data", "analyst", "IT", "cloud"],
        salary_min=0,
        max_pages=2,
    )
    for j in results[:5]:
        print(f"  {j['title']} | {j['location']} | {j['apply_url']}")
    print(f"\nTotal: {len(results)}")
