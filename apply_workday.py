#!/usr/bin/env python3
"""
applier/apply_workday.py
Playwright-based Workday form filler.

Workday is the hardest ATS — multi-step, heavy JS, tenant-specific URLs.

Flow:
  Step 1: My Information (name, email, phone, address, work auth)
  Step 2: My Experience (resume upload, work history, education)
  Step 3: Application Questions (custom per-job questions)
  Step 4: Self Identify (EEOC — skip/prefer not to answer)
  Step 5: Review + Submit

Detection: URLs contain .myworkdayjobs.com
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


def _ss(page: Page, name: str) -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = SCREENSHOT_DIR / f"{name}_{ts}.png"
    try:
        page.screenshot(path=str(p), full_page=True)
    except Exception:
        pass
    return str(p)


def _wait_click(page: Page, selector: str, timeout: int = 5000):
    try:
        el = page.wait_for_selector(selector, timeout=timeout)
        if el:
            el.click()
            return True
    except Exception:
        pass
    return False


def _fill_wd(page: Page, label_text: str, value: str) -> bool:
    """
    Fill a Workday field by finding its label then filling the associated input.
    Workday uses data-automation-id attributes extensively.
    """
    if not value:
        return False

    # Try data-automation-id approach
    for attr_val in [
        label_text.lower().replace(" ", ""),
        label_text.lower().replace(" ", "-"),
    ]:
        el = page.query_selector(f'input[data-automation-id*="{attr_val}" i]')
        if el and el.is_visible():
            el.fill(value)
            return True

    # Try finding by label text
    try:
        labels = page.query_selector_all('label')
        for label in labels:
            if label_text.lower() in (label.inner_text() or '').lower():
                for_attr = label.get_attribute('for')
                if for_attr:
                    inp = page.query_selector(f'#{for_attr}')
                    if inp and inp.is_visible():
                        inp.fill(value)
                        return True
                # Try sibling input
                parent = label.evaluate_handle('el => el.parentElement')
                inp = parent.query_selector('input') if parent else None
                if inp and inp.is_visible():
                    inp.fill(value)
                    return True
    except Exception:
        pass

    return False


def _answer_custom(q: str, profile: dict) -> str:
    q = q.lower()
    if any(w in q for w in ['right to work', 'work authorization', 'eligible', 'authorized', 'visa']):
        return 'Yes'
    if any(w in q for w in ['salary', 'compensation', 'expected', 'expectation']):
        return profile.get('salary_expectation_str', '$90,000 - $120,000 AUD')
    if any(w in q for w in ['notice', 'available', 'start date', 'when can']):
        return profile.get('availability', '2 weeks notice')
    if any(w in q for w in ['sponsor', 'sponsorship']):
        return 'No'
    if any(w in q for w in ['how did you', 'hear about', 'source', 'referral']):
        return 'Company careers website'
    if any(w in q for w in ['location', 'based', 'city', 'where are']):
        return 'Melbourne, VIC, Australia'
    if any(w in q for w in ['why', 'interest', 'motivation', 'why us', 'why this']):
        return (
            'I am excited about this opportunity at your organisation as it aligns with my '
            'expertise in IT consulting, data analytics, and Microsoft 365. I look forward '
            'to bringing my technical skills and analytical background to your team.'
        )
    return 'Please refer to my attached resume for details.'


def _handle_dropdown(page: Page, automation_id: str, value_text: str):
    """Open a Workday dropdown and select by visible text."""
    try:
        btn = page.query_selector(f'button[data-automation-id="{automation_id}"]')
        if not btn:
            btn = page.query_selector(f'[data-automation-id="{automation_id}"] button')
        if btn:
            btn.click()
            time.sleep(0.5)
            option = page.query_selector(f'li[data-automation-id="promptOption"]:has-text("{value_text}")')
            if option:
                option.click()
                return True
    except Exception:
        pass
    return False


def apply_workday(job: dict) -> dict:
    """Fill and submit Workday application (multi-step)."""
    profile = _load_profile()
    apply_url = job.get("apply_url", "")
    title = job.get("title", "")
    company = job.get("company", "")

    if not apply_url:
        return {"success": False, "error": "No apply_url"}

    print(f"  [workday/apply] {company} — {title}")
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
            page.goto(apply_url, wait_until="networkidle", timeout=40000)
        except Exception as e:
            browser.close()
            return {"success": False, "error": f"Page load: {e}"}

        # Wait for Workday to initialise
        time.sleep(3)
        ss = _ss(page, f"wd_loaded_{company}")

        try:
            # ── Check for "Apply" button on job detail page ──
            apply_btn = (
                page.query_selector('a[data-automation-id="applyButton"]')
                or page.query_selector('button[data-automation-id="applyButton"]')
                or page.query_selector('a:has-text("Apply")')
            )
            if apply_btn:
                apply_btn.click()
                time.sleep(3)
                page.wait_for_load_state("networkidle", timeout=20000)

            # ── Check for "Apply Manually" vs "Apply with LinkedIn" ──
            manual_btn = page.query_selector('button:has-text("Apply Manually"), a:has-text("Apply Manually")')
            if manual_btn:
                manual_btn.click()
                time.sleep(2)

            # ── Step 1: My Information ──
            print("  [workday/apply] Step 1: My Information")

            # Email
            for sel in ['input[data-automation-id="email"]', 'input[type="email"]', 'input[name*="email" i]']:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(profile["email"])
                    break

            # Check if there's a "sign in / create account" gate
            create_acc = page.query_selector('button:has-text("Create Account"), a:has-text("Create Account")')
            if create_acc:
                # Workday requires account — fill new account form
                _fill_wd(page, "First Name", profile["first_name"])
                _fill_wd(page, "Last Name", profile["last_name"])
                _fill_wd(page, "Email Address", profile["email"])
                _fill_wd(page, "Phone Number", profile["phone_au"])

                # Password for account (generate temp)
                import hashlib
                temp_pw = "Apply" + hashlib.md5(profile["email"].encode()).hexdigest()[:8] + "!"
                for pw_sel in ['input[type="password"]', 'input[data-automation-id="password"]']:
                    pw_el = page.query_selector(pw_sel)
                    if pw_el:
                        pw_el.fill(temp_pw)

                create_acc.click()
                time.sleep(3)

            # Standard My Information fields
            _fill_wd(page, "First Name", profile["first_name"])
            _fill_wd(page, "Last Name", profile["last_name"])
            _fill_wd(page, "Phone Number", profile["phone_au"])
            _fill_wd(page, "Address Line 1", profile["location"]["suburb"])
            _fill_wd(page, "City", profile["location"]["city"])
            _fill_wd(page, "Postal Code", profile["location"]["postcode"])

            # Country/State dropdowns
            _handle_dropdown(page, "country", "Australia")
            time.sleep(0.5)
            _handle_dropdown(page, "countryRegion", "Victoria")

            # Work authorisation
            # Look for "Are you legally authorised to work" type question
            for label_text in ["Are you legally", "Work Authorization", "Authorized to Work", "Right to Work"]:
                _fill_wd(page, label_text, "Yes")

            # Next / Save and Continue
            next_btn = (
                page.query_selector('button[data-automation-id="bottom-navigation-next-btn"]')
                or page.query_selector('button:has-text("Next")')
                or page.query_selector('button:has-text("Save and Continue")')
            )
            if next_btn:
                next_btn.click()
                time.sleep(3)
                page.wait_for_load_state("networkidle", timeout=15000)
            else:
                _ss(page, f"wd_no_next_{company}")

            # ── Step 2: My Experience ──
            print("  [workday/apply] Step 2: My Experience")

            # Resume upload
            resume_path = profile.get("resume_pdf_path", "")
            if resume_path and Path(resume_path).exists():
                # Click "Select files" or drag-drop zone
                upload_btn = (
                    page.query_selector('[data-automation-id="file-upload-drop-zone"]')
                    or page.query_selector('button:has-text("Select files")')
                    or page.query_selector('input[type="file"]')
                )
                if upload_btn:
                    tag = upload_btn.evaluate("el => el.tagName.toLowerCase()")
                    if tag == "input":
                        upload_btn.set_input_files(resume_path)
                    else:
                        upload_btn.click()
                        time.sleep(0.5)
                        file_inp = page.query_selector('input[type="file"]')
                        if file_inp:
                            file_inp.set_input_files(resume_path)
                    time.sleep(2)
                    print(f"  [workday/apply] Resume uploaded")

            # Work history (first entry)
            if profile.get("work_history"):
                wh = profile["work_history"][0]
                _fill_wd(page, "Job Title", wh.get("title", ""))
                _fill_wd(page, "Company", wh.get("company", ""))
                _fill_wd(page, "Location", wh.get("location", "Melbourne, VIC"))

            # Education (first entry)
            if profile.get("education"):
                edu = profile["education"][0]
                _fill_wd(page, "School or University", edu.get("institution", ""))
                _fill_wd(page, "Degree", edu.get("degree", ""))

            # Next
            next_btn = (
                page.query_selector('button[data-automation-id="bottom-navigation-next-btn"]')
                or page.query_selector('button:has-text("Next")')
            )
            if next_btn:
                next_btn.click()
                time.sleep(3)
                page.wait_for_load_state("networkidle", timeout=15000)

            # ── Step 3: Application Questions ──
            print("  [workday/apply] Step 3: Application Questions")

            # Find all visible question inputs
            questions = page.query_selector_all('[data-automation-id="formField"]')
            for q_el in questions:
                label_el = q_el.query_selector('label, [data-automation-id="formLabel"]')
                if not label_el:
                    continue
                q_text = label_el.inner_text().strip()

                inp = q_el.query_selector('input[type="text"]')
                if inp and inp.is_visible():
                    inp.fill(_answer_custom(q_text, profile))
                    continue

                ta = q_el.query_selector('textarea')
                if ta and ta.is_visible():
                    ta.fill(_answer_custom(q_text, profile))
                    continue

                # Radio — look for Yes option
                radios = q_el.query_selector_all('input[type="radio"]')
                if radios:
                    for r in radios:
                        label = r.evaluate("el => el.labels?.[0]?.innerText || ''")
                        if 'yes' in label.lower() or 'australia' in label.lower():
                            r.click()
                            break
                    else:
                        radios[0].click()

            # Next
            next_btn = (
                page.query_selector('button[data-automation-id="bottom-navigation-next-btn"]')
                or page.query_selector('button:has-text("Next")')
            )
            if next_btn:
                next_btn.click()
                time.sleep(2)

            # ── Step 4: Self Identify / EEOC — skip all (prefer not to answer) ──
            # Workday EEOC answers are voluntary — just click Next
            print("  [workday/apply] Step 4: Skipping demographic section")
            next_btn = (
                page.query_selector('button[data-automation-id="bottom-navigation-next-btn"]')
                or page.query_selector('button:has-text("Next")')
            )
            if next_btn:
                next_btn.click()
                time.sleep(2)

            # ── Step 5: Review ──
            print("  [workday/apply] Step 5: Review & Submit")
            pre_ss = _ss(page, f"wd_pre_submit_{company}")

            submit_btn = (
                page.query_selector('button[data-automation-id="bottom-navigation-finish-btn"]')
                or page.query_selector('button:has-text("Submit")')
            )

            if not submit_btn:
                browser.close()
                return {"success": False, "error": "Submit button not found", "screenshot_path": pre_ss}

            submit_btn.click()
            time.sleep(4)

            # ── Confirmation ──
            try:
                page.wait_for_selector(
                    '[data-automation-id="confirmation"], .confirmation, '
                    'h1:has-text("submitted"), h2:has-text("Thank")',
                    timeout=20000,
                )
            except PWTimeout:
                post_ss = _ss(page, f"wd_post_submit_{company}")
                # Check URL for confirmation
                if any(w in page.url.lower() for w in ["confirm", "thank", "success"]):
                    browser.close()
                    return {"success": True, "screenshot_path": post_ss}
                browser.close()
                return {"success": False, "error": "No confirmation detected", "screenshot_path": post_ss}

            post_ss = _ss(page, f"wd_applied_{company}")
            print(f"  [workday/apply] Applied! {post_ss}")
            browser.close()
            return {"success": True, "screenshot_path": post_ss}

        except Exception as e:
            err_ss = _ss(page, f"wd_error_{company}")
            browser.close()
            return {"success": False, "error": str(e), "screenshot_path": err_ss}


if __name__ == "__main__":
    test_job = {
        "title": "Technology Consultant",
        "company": "Accenture Australia",
        "ats_type": "workday",
        "apply_url": "https://accenture.wd3.myworkdayjobs.com/AccentureCareers/job/Melbourne/TEST",
    }
    print(apply_workday(test_job))
