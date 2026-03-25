#!/usr/bin/env python3
"""
applier/apply_greenhouse.py
Playwright-based Greenhouse form filler.

Greenhouse apply page:
  https://boards.greenhouse.io/{board_token}/jobs/{job_id}
  Or direct apply: https://boards.greenhouse.io/{token}/jobs/{id}#app

Form sections:
  - Basic info (name, email, phone, location)
  - Resume + cover letter upload
  - Education section
  - Employment / work history
  - Custom questions
  - EEOC/demographic (skip — not required)
  - Submit
"""

import os
import sys
import time
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeout


PROFILE_PATH = ROOT / "candidate_profile.json"
SCREENSHOT_DIR = ROOT / "logs" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


def _load_profile() -> dict:
    with open(PROFILE_PATH) as f:
        return json.load(f)


def _screenshot(page: Page, name: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = SCREENSHOT_DIR / f"{name}_{ts}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        pass
    return str(path)


def _answer_custom(question: str, profile: dict) -> str:
    q = question.lower()
    if any(w in q for w in ["right to work", "work in australia", "eligible", "visa"]):
        return "Yes"
    if any(w in q for w in ["salary", "compensation", "expected"]):
        return profile.get("salary_expectation_str", "$90,000 - $120,000 AUD")
    if any(w in q for w in ["notice", "available", "start date"]):
        return profile.get("availability", "2 weeks notice")
    if any(w in q for w in ["how did you hear", "referral", "source", "find"]):
        return "Company careers page"
    if any(w in q for w in ["sponsorship", "sponsor"]):
        return "No"
    if any(w in q for w in ["location", "based", "city"]):
        return "Melbourne, VIC, Australia"
    if any(w in q for w in ["linkedin"]):
        return profile.get("linkedin_url", "")
    if any(w in q for w in ["why", "interest", "motivat"]):
        return (
            f"I am highly interested in this role as it aligns with my expertise in "
            f"IT consulting, data analytics, and Microsoft 365 administration. "
            f"I am excited to contribute to your team and grow professionally."
        )
    return "Please refer to my attached resume for details."


def _fill_text_field(page: Page, selectors: list, value: str):
    """Try multiple selectors, fill first one found."""
    for sel in selectors:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.fill(value)
            return True
    return False


def apply_greenhouse(job: dict) -> dict:
    """Fill and submit Greenhouse application."""
    profile = _load_profile()
    apply_url = job.get("apply_url", "")
    title = job.get("title", "")
    company = job.get("company", "")
    board_token = job.get("ats_board_token", "")

    if not apply_url:
        return {"success": False, "error": "No apply_url"}

    print(f"  [greenhouse/apply] {company} — {title}")
    print(f"  URL: {apply_url}")

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
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        try:
            page.goto(apply_url, wait_until="networkidle", timeout=30000)
        except Exception as e:
            browser.close()
            return {"success": False, "error": f"Page load error: {e}"}

        try:
            # ── Basic info ──
            _fill_text_field(page,
                ['input#first_name', 'input[name="job_application[first_name]"]'],
                profile["first_name"])

            _fill_text_field(page,
                ['input#last_name', 'input[name="job_application[last_name]"]'],
                profile["last_name"])

            _fill_text_field(page,
                ['input#email', 'input[name="job_application[email]"]'],
                profile["email"])

            _fill_text_field(page,
                ['input#phone', 'input[name="job_application[phone]"]'],
                profile["phone_au"])

            _fill_text_field(page,
                ['input[name="job_application[location]"]', 'input#location'],
                f"{profile['location']['city']}, {profile['location']['state']}, Australia")

            # ── Resume upload ──
            resume_path = profile.get("resume_pdf_path", "")
            if resume_path and Path(resume_path).exists():
                # Greenhouse has a specific resume upload area
                resume_input = (
                    page.query_selector('input#resume')
                    or page.query_selector('input[name="job_application[resume]"]')
                    or page.query_selector('.resume-upload input[type="file"]')
                )
                if resume_input:
                    resume_input.set_input_files(resume_path)
                    time.sleep(1)
                    print(f"  [greenhouse/apply] Resume uploaded")
                else:
                    # Try clicking the upload button area
                    upload_btn = page.query_selector('.attach-resume button, #resume_prompt_button')
                    if upload_btn:
                        upload_btn.click()
                        time.sleep(0.5)
                        file_input = page.query_selector('input[type="file"]')
                        if file_input:
                            file_input.set_input_files(resume_path)
                            time.sleep(1)

            # ── Cover letter upload (optional) ──
            cover_path = profile.get("cover_letter_template_path", "")
            if cover_path and Path(cover_path).exists():
                cover_input = (
                    page.query_selector('input#cover_letter')
                    or page.query_selector('input[name="job_application[cover_letter]"]')
                )
                if cover_input:
                    cover_input.set_input_files(cover_path)
                    time.sleep(0.5)

            # ── LinkedIn / website ──
            _fill_text_field(page,
                ['input[name="job_application[answers_attributes][0][text_value]"]',
                 'input[placeholder*="LinkedIn" i]',
                 '#job_application_answers_attributes_0_text_value'],
                profile.get("linkedin_url", ""))

            # ── Education section ──
            edu = profile.get("education", [{}])[0]
            _fill_text_field(page,
                ['input[name*="school_name"]', '#job_application_educations_attributes_0_school_name'],
                edu.get("institution", ""))
            _fill_text_field(page,
                ['input[name*="degree"]', '#job_application_educations_attributes_0_degree'],
                edu.get("degree", ""))
            _fill_text_field(page,
                ['input[name*="discipline"]', '#job_application_educations_attributes_0_discipline'],
                "Business Analytics / Information Technology")
            _fill_text_field(page,
                ['input[name*="end_date"]', 'input[name*="graduation"]'],
                str(edu.get("year", "2024")))

            # ── Employment history ──
            if profile.get("work_history"):
                job0 = profile["work_history"][0]
                _fill_text_field(page,
                    ['input[name*="company_name"]', '#job_application_employments_attributes_0_company_name'],
                    job0.get("company", ""))
                _fill_text_field(page,
                    ['input[name*="job_title"]', '#job_application_employments_attributes_0_title'],
                    job0.get("title", ""))

            # ── Custom questions ──
            # Greenhouse renders custom questions with class "field"
            custom_fields = page.query_selector_all('.field, .custom-field, .question')
            for field in custom_fields:
                label_el = field.query_selector('label')
                if not label_el:
                    continue
                q_text = label_el.inner_text().strip()

                # Text input
                inp = field.query_selector('input[type="text"]')
                if inp and inp.is_visible():
                    inp.fill(_answer_custom(q_text, profile))
                    continue

                # Textarea
                ta = field.query_selector('textarea')
                if ta and ta.is_visible():
                    ta.fill(_answer_custom(q_text, profile))
                    continue

                # Select
                sel_el = field.query_selector('select')
                if sel_el:
                    options = sel_el.query_selector_all('option')
                    for opt in options:
                        val = opt.get_attribute('value') or ''
                        txt = opt.inner_text().lower()
                        if any(w in txt for w in ['yes', 'australia', 'melbourne', 'no sponsor']):
                            sel_el.select_option(val)
                            break
                    continue

                # Checkbox — check if "yes" / agreement
                cb = field.query_selector('input[type="checkbox"]')
                if cb and 'agree' in q_text.lower():
                    cb.check()

            # ── EEOC / Demographic section — skip all ──
            # These are voluntary — Greenhouse marks them clearly
            eeoc_section = page.query_selector('.eeoc, #eeoc_fields, .demographic')
            # Just leave them at default (prefer not to answer)

            # ── Pre-submit screenshot ──
            pre_ss = _screenshot(page, f"gh_pre_submit_{company}")
            print(f"  [greenhouse/apply] Pre-submit screenshot: {pre_ss}")

            # ── Submit ──
            submit = (
                page.query_selector('input[type="submit"]')
                or page.query_selector('button[type="submit"]')
                or page.query_selector('#submit_app')
                or page.query_selector('button:has-text("Submit Application")')
            )

            if not submit:
                browser.close()
                return {"success": False, "error": "Submit button not found", "screenshot_path": pre_ss}

            submit.click()

            # ── Wait for confirmation ──
            try:
                page.wait_for_url("**/confirmation**", timeout=15000)
            except PWTimeout:
                try:
                    page.wait_for_selector(
                        '.confirmation, .success, h1:has-text("Application"), h2:has-text("Thank")',
                        timeout=10000,
                    )
                except PWTimeout:
                    post_ss = _screenshot(page, f"gh_post_submit_{company}")
                    browser.close()
                    # Check if URL changed
                    if "confirmation" in page.url or "thank" in page.url.lower():
                        return {"success": True, "screenshot_path": post_ss}
                    return {"success": False, "error": "No confirmation detected", "screenshot_path": post_ss}

            post_ss = _screenshot(page, f"gh_applied_{company}")
            print(f"  [greenhouse/apply] Applied! Screenshot: {post_ss}")
            browser.close()
            return {"success": True, "screenshot_path": post_ss}

        except Exception as e:
            err_ss = _screenshot(page, f"gh_error_{company}")
            browser.close()
            return {"success": False, "error": str(e), "screenshot_path": err_ss}


if __name__ == "__main__":
    test_job = {
        "title": "Technology Consultant",
        "company": "Capgemini Australia",
        "ats_type": "greenhouse",
        "ats_board_token": "capgemini",
        "apply_url": "https://boards.greenhouse.io/capgemini/jobs/TEST-ID",
    }
    print(apply_greenhouse(test_job))
