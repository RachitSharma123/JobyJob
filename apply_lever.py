#!/usr/bin/env python3
"""
applier/apply_lever.py
Playwright-based Lever form filler.

Lever apply page structure:
  https://jobs.lever.co/{company}/{job_id}/apply
  - Full name, Email, Phone, Location
  - Resume upload (PDF)
  - Cover letter textarea (optional)
  - LinkedIn URL
  - Custom questions (detected + AI-answered)
  - Submit button
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
    page.screenshot(path=str(path), full_page=True)
    return str(path)


def _answer_custom_question(question: str, profile: dict) -> str:
    """Simple rule-based answers for common Lever custom questions."""
    q = question.lower()

    if any(w in q for w in ["right to work", "work in australia", "visa", "eligible to work"]):
        return "Yes, I have the right to work in Australia."

    if any(w in q for w in ["salary", "compensation", "expected", "expectation"]):
        return profile.get("salary_expectation_str", "$90,000 - $120,000 AUD")

    if any(w in q for w in ["notice period", "start", "available", "availability"]):
        return profile.get("availability", "2 weeks notice")

    if any(w in q for w in ["how did you hear", "referral", "source"]):
        return "Company careers page"

    if any(w in q for w in ["why", "interest", "motivation", "passionate"]):
        return (
            f"I am excited about this opportunity as it aligns with my background in "
            f"IT consulting, data analytics, and Microsoft 365 administration. "
            f"I am eager to bring my technical and analytical skills to your team."
        )

    if any(w in q for w in ["experience", "years", "background"]):
        return f"I have {profile.get('years_experience', 4)} years of experience in IT and analytics roles in Melbourne."

    if any(w in q for w in ["location", "based", "relocat"]):
        return "I am based in Melbourne, VIC and am not looking to relocate."

    if any(w in q for w in ["sponsorship", "sponsor"]):
        return "No, I do not require sponsorship."

    # Default fallback
    return "Please refer to my resume and cover letter for detailed information."


def apply_lever(job: dict) -> dict:
    """
    Fill and submit a Lever job application.

    Returns:
        {"success": True, "screenshot_path": "..."} on success
        {"success": False, "error": "..."} on failure
    """
    profile = _load_profile()
    apply_url = job.get("apply_url", "")
    title = job.get("title", "")
    company = job.get("company", "")

    if not apply_url:
        return {"success": False, "error": "No apply_url in job dict"}

    # Ensure URL ends with /apply
    if not apply_url.endswith("/apply"):
        apply_url = apply_url.rstrip("/") + "/apply"

    print(f"  [lever/apply] {company} — {title}")
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
            accept_downloads=True,
        )
        page = ctx.new_page()

        try:
            page.goto(apply_url, wait_until="networkidle", timeout=30000)
        except PWTimeout:
            browser.close()
            return {"success": False, "error": "Page load timeout"}
        except Exception as e:
            browser.close()
            return {"success": False, "error": f"Page load error: {e}"}

        # Check page loaded correctly
        if "lever.co" not in page.url and "jobs.lever.co" not in page.url:
            _screenshot(page, f"lever_wrong_page_{company}")
            browser.close()
            return {"success": False, "error": f"Unexpected URL: {page.url}"}

        try:
            # ── Full name ──
            name_input = page.query_selector('input[name="name"]')
            if name_input:
                name_input.fill(profile["full_name"])

            # ── Email ──
            email_input = page.query_selector('input[name="email"]')
            if email_input:
                email_input.fill(profile["email"])

            # ── Phone ──
            phone_input = page.query_selector('input[name="phone"]')
            if phone_input:
                phone_input.fill(profile["phone_au"])

            # ── Location / Current company / Org ──
            for selector, value in [
                ('input[name="org"]', profile["current_company"]),
                ('input[name="location"]', profile["location"]["city"]),
                ('input[name="currentCompany"]', profile["current_company"]),
            ]:
                el = page.query_selector(selector)
                if el:
                    el.fill(value)

            # ── LinkedIn ──
            linkedin_input = page.query_selector('input[name="urls[LinkedIn]"]')
            if not linkedin_input:
                linkedin_input = page.query_selector('input[placeholder*="LinkedIn" i]')
            if linkedin_input:
                linkedin_input.fill(profile.get("linkedin_url", ""))

            # ── Resume upload ──
            resume_path = profile.get("resume_pdf_path", "")
            if resume_path and Path(resume_path).exists():
                file_input = page.query_selector('input[type="file"]')
                if file_input:
                    file_input.set_input_files(resume_path)
                    time.sleep(1)
                    print(f"  [lever/apply] Resume uploaded")
            else:
                print(f"  [lever/apply] WARNING: Resume not found at {resume_path}")

            # ── Cover letter textarea ──
            cl_textarea = page.query_selector('textarea[name="comments"]')
            if not cl_textarea:
                cl_textarea = page.query_selector('textarea[placeholder*="cover" i]')
            if cl_textarea:
                cover = (
                    f"Dear Hiring Team,\n\n"
                    f"{profile.get('cover_letter_intro', '')}\n\n"
                    f"I am applying for the {title} position at {company}. "
                    f"With my background in {', '.join(profile.get('skills', [])[:5])}, "
                    f"I am confident I can contribute meaningfully to your team.\n\n"
                    f"Kind regards,\n{profile['full_name']}"
                )
                cl_textarea.fill(cover)

            # ── Custom questions ──
            # Lever renders these as divs with class "application-question"
            custom_sections = page.query_selector_all(".application-question")
            for section in custom_sections:
                label_el = section.query_selector("label, .application-label")
                if not label_el:
                    continue
                question_text = label_el.inner_text().strip()

                # Text input
                text_input = section.query_selector('input[type="text"], input[type="number"]')
                if text_input:
                    answer = _answer_custom_question(question_text, profile)
                    text_input.fill(answer)
                    continue

                # Textarea
                textarea = section.query_selector("textarea")
                if textarea:
                    answer = _answer_custom_question(question_text, profile)
                    textarea.fill(answer)
                    continue

                # Select / dropdown
                select_el = section.query_selector("select")
                if select_el:
                    # Try to select "Yes" or first non-empty option
                    options = select_el.query_selector_all("option")
                    for opt in options:
                        val = opt.get_attribute("value") or ""
                        text = opt.inner_text().lower()
                        if "yes" in text or "australia" in text or val not in ["", "null", "none"]:
                            select_el.select_option(val)
                            break
                    continue

                # Radio buttons — pick "Yes" or first option
                radios = section.query_selector_all('input[type="radio"]')
                if radios:
                    for radio in radios:
                        label = radio.evaluate("el => el.labels[0]?.innerText || ''").lower()
                        if "yes" in label or "australia" in label:
                            radio.click()
                            break
                    else:
                        radios[0].click()

            # ── Screenshot before submit ──
            pre_screenshot = _screenshot(page, f"lever_pre_submit_{company}")
            print(f"  [lever/apply] Pre-submit screenshot: {pre_screenshot}")

            # ── Submit ──
            submit_btn = (
                page.query_selector('button[type="submit"]')
                or page.query_selector('input[type="submit"]')
                or page.query_selector('button:has-text("Submit application")')
                or page.query_selector('button:has-text("Apply")')
            )

            if not submit_btn:
                browser.close()
                return {"success": False, "error": "Submit button not found"}

            submit_btn.click()

            # ── Wait for confirmation ──
            try:
                page.wait_for_selector(
                    ".success-message, .confirmation, h1:has-text('Application submitted'), "
                    "h2:has-text('Thanks'), .thank-you",
                    timeout=15000,
                )
            except PWTimeout:
                # Check URL changed at least
                if apply_url not in page.url:
                    pass  # probably submitted OK
                else:
                    post_screenshot = _screenshot(page, f"lever_post_submit_{company}")
                    browser.close()
                    return {
                        "success": False,
                        "error": "No confirmation page detected after submit",
                        "screenshot_path": post_screenshot,
                    }

            # ── Final screenshot ──
            post_screenshot = _screenshot(page, f"lever_applied_{company}")
            print(f"  [lever/apply] Applied successfully! Screenshot: {post_screenshot}")

            browser.close()
            return {"success": True, "screenshot_path": post_screenshot}

        except Exception as e:
            err_screenshot = _screenshot(page, f"lever_error_{company}")
            browser.close()
            return {"success": False, "error": str(e), "screenshot_path": err_screenshot}


if __name__ == "__main__":
    # Test with a specific job
    test_job = {
        "external_id": "lever_thoughtworks_test",
        "title": "Technology Consultant",
        "company": "Thoughtworks",
        "firm_name": "Thoughtworks Australia",
        "ats_type": "lever",
        "ats_company_id": "thoughtworks",
        "apply_url": "https://jobs.lever.co/thoughtworks/TEST-ID-HERE/apply",
        "description": "Test job",
    }
    result = apply_lever(test_job)
    print(result)
