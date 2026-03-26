#!/usr/bin/env python3
"""
scraper_router.py
Reads firms.json, routes each firm to the correct ATS scraper,
deduplicates, and returns a unified list of job dicts.

Usage:
  from scraper.scraper_router import run_all_scrapers
  jobs = run_all_scrapers()

Or run directly:
  python3 scraper/scraper_router.py
"""

import json
import sys
from pathlib import Path
from datetime import date

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "firms.json").exists() else HERE.parent
FIRMS_FILE = ROOT / "firms.json"

sys.path.insert(0, str(ROOT))
try:
    from scraper.lever_scraper import scrape_lever
    from scraper.workday_scraper import scrape_workday
    from scraper.greenhouse_scraper import scrape_greenhouse
except ModuleNotFoundError:
    # Flat-repo fallback (used by Streamlit Cloud in this repository layout)
    from lever_scraper import scrape_lever
    from workday_scraper import scrape_workday
    from greenhouse_scraper import scrape_greenhouse
try:
    from job_suppliers import fetchadzuna, fetchcareerjet, fetchseek
except ModuleNotFoundError:
    fetchadzuna = fetchcareerjet = fetchseek = None


def _supplier_match(job: dict, location_filter: str, role_keywords: list[str], salary_min: int) -> bool:
    location = (job.get("location") or "").lower()
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()[:1000]
    sal = job.get("salary_min")

    if location_filter and location_filter.lower() not in location and "australia" not in location and "remote" not in location:
        return False
    if role_keywords and not any(k.lower() in f"{title} {desc}" for k in role_keywords):
        return False
    if salary_min and sal and sal < salary_min:
        return False
    return True


def _load_firms() -> list[dict]:
    with open(FIRMS_FILE) as f:
        firms = json.load(f)
    return [f for f in firms if f.get("active", True)]


def _dedup(jobs: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for j in jobs:
        key = j.get("external_id") or f"{j['company'].lower()}_{j['title'].lower()}"
        if key not in seen:
            seen.add(key)
            out.append(j)
    return out


def run_all_scrapers(
    ats_filter: list[str] = None,
    firm_filter: list[str] = None,
) -> list[dict]:
    """
    Run all scrapers defined in firms.json.

    Args:
        ats_filter: Only run specific ATS types e.g. ["lever", "workday"]
        firm_filter: Only run specific firm names e.g. ["Deloitte Australia"]

    Returns:
        Deduplicated list of normalized job dicts.
    """
    firms = _load_firms()
    all_jobs = []

    for firm in firms:
        name = firm["name"]
        ats = firm["ats"]

        if ats_filter and ats not in ats_filter:
            continue
        if firm_filter and name not in firm_filter:
            continue

        print(f"\n[router] Scraping {name} ({ats})...")

        common = dict(
            firm_name=name,
            location_filter=firm.get("location_filter", "Melbourne"),
            role_keywords=firm.get("role_keywords", []),
            salary_min=firm.get("salary_min", 0),
        )

        try:
            if ats == "lever":
                jobs = scrape_lever(
                    company_id=firm["company_id"],
                    **common,
                )

            elif ats == "workday":
                if not firm.get("jobs_api"):
                    print(f"  [router] {name}: no jobs_api configured, skipping")
                    continue
                jobs = scrape_workday(
                    jobs_api=firm["jobs_api"],
                    **common,
                    max_pages=3,
                )

            elif ats == "greenhouse":
                jobs = scrape_greenhouse(
                    board_token=firm["board_token"],
                    **common,
                )

            elif ats == "custom":
                print(f"  [router] {name}: custom scraper not yet implemented, skipping")
                continue

            elif ats == "adzuna":
                if fetchadzuna is None:
                    print(f"  [router] {name}: supplier module unavailable, skipping")
                    continue
                raw = fetchadzuna(
                    what=firm.get("query", "systems analyst"),
                    where=firm.get("location_filter", "Melbourne"),
                )
                jobs = [j for j in raw if _supplier_match(j, common["location_filter"], common["role_keywords"], common["salary_min"])]
                print(f"  [adzuna] {name}: {len(raw)} total → {len(jobs)} matched")

            elif ats == "careerjet":
                if fetchcareerjet is None:
                    print(f"  [router] {name}: supplier module unavailable, skipping")
                    continue
                raw = fetchcareerjet(
                    what=firm.get("query", "systems analyst"),
                    where=firm.get("location_filter", "Melbourne"),
                )
                jobs = [j for j in raw if _supplier_match(j, common["location_filter"], common["role_keywords"], common["salary_min"])]
                print(f"  [careerjet] {name}: {len(raw)} total → {len(jobs)} matched")

            elif ats == "seek":
                if fetchseek is None:
                    print(f"  [router] {name}: supplier module unavailable, skipping")
                    continue
                raw = fetchseek(
                    what=firm.get("query", "systems analyst"),
                    where=firm.get("location_filter", "Melbourne"),
                )
                jobs = [j for j in raw if _supplier_match(j, common["location_filter"], common["role_keywords"], common["salary_min"])]
                print(f"  [seek] {name}: {len(raw)} total → {len(jobs)} matched")

            else:
                print(f"  [router] {name}: unknown ATS '{ats}', skipping")
                continue

        except Exception as e:
            print(f"  [router] {name}: EXCEPTION — {e}")
            jobs = []

        # Stamp today's date
        today = str(date.today())
        for j in jobs:
            j.setdefault("date_found", today)

        all_jobs.extend(jobs)

    deduped = _dedup(all_jobs)
    print(f"\n[router] Total: {len(all_jobs)} raw → {len(deduped)} after dedup")
    return deduped


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--ats", nargs="+", help="Filter by ATS type: lever workday greenhouse adzuna careerjet seek")
    parser.add_argument("--firm", nargs="+", help="Filter by firm name")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    jobs = run_all_scrapers(
        ats_filter=args.ats,
        firm_filter=args.firm,
    )

    if args.json:
        print(json.dumps(jobs, indent=2, default=str))
    else:
        print(f"\n{'='*60}")
        for j in jobs:
            sal = ""
            if j.get("salary_min"):
                sal = f" | ${j['salary_min']:,}"
                if j.get("salary_max"):
                    sal += f"–${j['salary_max']:,}"
            print(f"  [{j['ats_type']}] {j['company']} | {j['title']}{sal}")
            print(f"    {j['apply_url']}")
        print(f"\n{len(jobs)} jobs total")
