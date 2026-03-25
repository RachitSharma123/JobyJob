#!/usr/bin/env python3
"""
greenhouse_scraper.py
Fetches job postings from Greenhouse's public Job Board API.
No auth required — fully open:
  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
"""

import httpx
import re
from typing import Optional
from html.parser import HTMLParser


class _HTMLStripper(HTMLParser):
    """Strip HTML tags from job descriptions."""
    def __init__(self):
        super().__init__()
        self.text_parts = []

    def handle_data(self, data):
        self.text_parts.append(data)

    def get_text(self):
        return " ".join(self.text_parts).strip()


def _strip_html(html: str) -> str:
    if not html:
        return ""
    stripper = _HTMLStripper()
    try:
        stripper.feed(html)
        return stripper.get_text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", html).strip()


def _parse_salary_from_text(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    patterns = [
        r"\$(\d{2,3})[Kk][\s\-–]+\$?(\d{2,3})[Kk]",
        r"\$(\d{2,3}),000[\s\-–]+\$?(\d{2,3}),000",
        r"(\d{2,3})[Kk][\s\-–]+(\d{2,3})[Kk]",
        r"AUD\s*(\d{2,3}),000[\s\-–]+(\d{2,3}),000",
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


def _location_match(job: dict, location_filter: str) -> bool:
    if not location_filter:
        return True
    offices = job.get("offices", [])
    location_names = [o.get("name", "").lower() for o in offices]
    all_locations = " ".join(location_names)
    return (
        location_filter.lower() in all_locations
        or "australia" in all_locations
        or "remote" in all_locations
    )


def _keyword_match(title: str, description: str, keywords: list[str]) -> bool:
    haystack = (title + " " + description[:800]).lower()
    return any(kw.lower() in haystack for kw in keywords)


def scrape_greenhouse(
    board_token: str,
    firm_name: str,
    location_filter: str = "Melbourne",
    role_keywords: list[str] = None,
    salary_min: int = 0,
) -> list[dict]:
    """
    Fetch and filter jobs from Greenhouse public board API.
    board_token examples: "ey", "capgemini", "atturra", "arqgroup"
    """
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    role_keywords = role_keywords or []

    try:
        resp = httpx.get(url, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        data = resp.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            print(f"  [greenhouse] {board_token}: board not found (404) — token may be wrong")
        else:
            print(f"  [greenhouse] {board_token}: HTTP {e.response.status_code}")
        return []
    except Exception as e:
        print(f"  [greenhouse] {board_token}: {e}")
        return []

    all_postings = data.get("jobs", [])
    jobs = []

    for p in all_postings:
        job_id = str(p.get("id", ""))
        title = p.get("title", "")
        apply_url = p.get("absolute_url", "")

        # Location filter
        if not _location_match(p, location_filter):
            continue

        # Description — content=true gives us full HTML content
        content = p.get("content", "") or ""
        description = _strip_html(content)[:2000]

        # Keyword filter
        if role_keywords and not _keyword_match(title, description, role_keywords):
            continue

        # Location string
        offices = p.get("offices", [])
        location = offices[0].get("name", "Melbourne, VIC") if offices else "Melbourne, VIC"

        # Salary
        salary_min_found, salary_max_found = _parse_salary_from_text(description)
        if salary_min and salary_min_found and salary_min_found < salary_min:
            continue

        # Department
        departments = p.get("departments", [])
        department = departments[0].get("name", "") if departments else ""

        jobs.append({
            "external_id": f"greenhouse_{board_token}_{job_id}",
            "title": title,
            "company": firm_name,
            "location": location,
            "salary_min": salary_min_found,
            "salary_max": salary_max_found,
            "apply_url": apply_url,
            "job_url": apply_url,
            "source": "greenhouse",
            "ats_type": "greenhouse",
            "firm_name": firm_name,
            "ats_job_id": job_id,
            "ats_board_token": board_token,
            "department": department,
            "description": description,
        })

    print(f"  [greenhouse] {firm_name}: {len(all_postings)} total → {len(jobs)} matched")
    return jobs


if __name__ == "__main__":
    # Quick test
    results = scrape_greenhouse(
        board_token="capgemini",
        firm_name="Capgemini Australia",
        location_filter="Melbourne",
        role_keywords=["technology", "data", "analyst", "consultant", "IT", "cloud"],
        salary_min=0,
    )
    for j in results[:5]:
        print(f"  {j['title']} | {j['location']} | {j['apply_url']}")
    print(f"\nTotal: {len(results)}")
