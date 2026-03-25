#!/usr/bin/env python3
"""
lever_scraper.py
Fetches Lever job postings via Playwright (intercepts the API JSON call).
Lever's api.lever.co blocks datacenter IPs via Cloudflare.
Strategy: load jobs.lever.co/{company} in headless browser,
intercept the XHR call to api.lever.co, grab JSON response.
Falls back to DOM scraping if intercept fails.
"""

import json
import re
import time
from typing import Optional
from playwright.sync_api import sync_playwright, Response


def _parse_salary(text: str) -> tuple[Optional[int], Optional[int]]:
    if not text:
        return None, None
    for p in [
        r"\$(\d{2,3})[Kk][\s\-–]+\$?(\d{2,3})[Kk]",
        r"\$(\d{2,3}),000[\s\-–]+\$?(\d{2,3}),000",
        r"(\d{2,3})[Kk][\s\-–]+(\d{2,3})[Kk]",
    ]:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            lo = int(m.group(1).replace(",", ""))
            hi = int(m.group(2).replace(",", ""))
            lo = lo * 1000 if lo < 1000 else lo
            hi = hi * 1000 if hi < 1000 else hi
            return lo, hi
    return None, None


def _kw_match(title: str, desc: str, keywords: list) -> bool:
    h = (title + " " + desc[:500]).lower()
    return any(k.lower() in h for k in keywords)


def _loc_match(loc: str, filt: str) -> bool:
    if not filt:
        return True
    t = loc.lower()
    return filt.lower() in t or "australia" in t or "remote" in t or t == ""


def _normalize(p: dict, company_id: str, firm_name: str) -> dict:
    pid = p.get("id", "")
    title = p.get("text", "")
    apply_url = p.get("applyUrl") or f"https://jobs.lever.co/{company_id}/{pid}"
    hosted_url = p.get("hostedUrl") or apply_url
    loc = (p.get("categories") or {}).get("location", "") or "Melbourne, VIC"

    parts = []
    for s in (p.get("descriptionBody") or {}).get("body", []):
        if isinstance(s, dict):
            parts.append(s.get("text", ""))
    for lst in (p.get("lists") or []):
        parts.append(lst.get("text", ""))
        for item in (lst.get("content") or []):
            if isinstance(item, dict):
                parts.append(item.get("text", ""))
    desc = " ".join(parts).strip()[:2000]
    sal_min, sal_max = _parse_salary(desc)

    return {
        "external_id": f"lever_{company_id}_{pid}",
        "title": title,
        "company": firm_name,
        "location": loc,
        "salary_min": sal_min,
        "salary_max": sal_max,
        "apply_url": apply_url,
        "job_url": hosted_url,
        "source": "lever",
        "ats_type": "lever",
        "firm_name": firm_name,
        "ats_job_id": pid,
        "ats_company_id": company_id,
        "description": desc,
    }


def _playwright_fetch(company_id: str) -> Optional[list]:
    intercepted = []

    def on_response(resp: Response):
        if "api.lever.co/v0/postings" in resp.url and "mode=json" in resp.url:
            try:
                data = resp.json()
                if isinstance(data, list):
                    intercepted.extend(data)
            except Exception:
                pass

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()
        page.on("response", on_response)

        try:
            page.goto(
                f"https://jobs.lever.co/{company_id}",
                wait_until="networkidle",
                timeout=35000,
            )
            time.sleep(2)
        except Exception as e:
            print(f"  [lever/pw] {company_id}: {e}")
            browser.close()
            return None

        if intercepted:
            browser.close()
            return intercepted

        # DOM fallback — parse job cards directly
        print(f"  [lever/pw] {company_id}: XHR not intercepted, parsing DOM")
        dom_jobs = []
        try:
            cards = page.query_selector_all(".posting")
            for card in cards:
                t_el = card.query_selector("h5")
                title = t_el.inner_text().strip() if t_el else ""
                a_el = card.query_selector("a.posting-title")
                href = a_el.get_attribute("href") if a_el else ""
                l_el = card.query_selector(".sort-by-location")
                loc = l_el.inner_text().strip() if l_el else ""
                if title and href:
                    pid = href.rstrip("/").split("/")[-1]
                    dom_jobs.append({
                        "id": pid,
                        "text": title,
                        "hostedUrl": href,
                        "applyUrl": href + "/apply",
                        "categories": {"location": loc},
                        "descriptionBody": {"body": []},
                        "lists": [],
                    })
        except Exception as e:
            print(f"  [lever/pw] {company_id}: DOM error — {e}")

        browser.close()
        return dom_jobs or None


def scrape_lever(
    company_id: str,
    location_filter: str = "Melbourne",
    role_keywords: list = None,
    salary_min: int = 0,
    firm_name: str = "",
) -> list:
    firm_name = firm_name or company_id
    role_keywords = role_keywords or []

    raw = _playwright_fetch(company_id)
    if not raw:
        return []

    jobs = []
    for p in raw:
        loc = (p.get("categories") or {}).get("location", "")
        if not _loc_match(loc, location_filter):
            continue
        job = _normalize(p, company_id, firm_name)
        if role_keywords and not _kw_match(job["title"], job["description"], role_keywords):
            continue
        if salary_min and job["salary_min"] and job["salary_min"] < salary_min:
            continue
        jobs.append(job)

    print(f"  [lever] {firm_name}: {len(raw)} total → {len(jobs)} matched")
    return jobs


if __name__ == "__main__":
    results = scrape_lever(
        company_id="thoughtworks",
        location_filter="Melbourne",
        role_keywords=["consultant", "data", "analyst", "technology"],
        salary_min=0,
        firm_name="Thoughtworks Australia",
    )
    for j in results:
        sal = f" | ${j['salary_min']:,}" if j.get("salary_min") else ""
        print(f"  {j['title']} | {j['location']}{sal}")
    print(f"\nTotal: {len(results)}")
