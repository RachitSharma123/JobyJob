#!/usr/bin/env python3
"""
ai/tailor_resume.py
Uses Claude/OpenAI to tailor resume and generate a targeted cover letter
based on the job description. Saves output as text for the applier to use.

Called by: applier scripts before filling cover letter textarea.
"""

import os
import sys
import json
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PROFILE_PATH = ROOT / "candidate_profile.json"


def _load_env():
    env_file = Path.home() / ".openclaw" / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()


def _call_claude(prompt: str) -> str:
    """Call Anthropic Claude API."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _call_openai(prompt: str) -> str:
    """Fallback: OpenAI API."""
    import openai
    client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=800,
    )
    return resp.choices[0].message.content.strip()


def _call_ai(prompt: str) -> str:
    """Try Claude first, fall back to OpenAI."""
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            return _call_claude(prompt)
        except Exception as e:
            print(f"  [ai] Claude failed: {e}, trying OpenAI...")
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _call_openai(prompt)
        except Exception as e:
            print(f"  [ai] OpenAI failed: {e}")
    return ""


def generate_cover_letter(job: dict) -> str:
    """
    Generate a tailored cover letter for a specific job.
    Returns plain text cover letter.
    """
    with open(PROFILE_PATH) as f:
        profile = json.load(f)

    title = job.get("title", "")
    company = job.get("company", "")
    description = (job.get("description", "") or "")[:1000]

    prompt = f"""Write a professional, concise cover letter (3 paragraphs, under 250 words) for:

Job: {title} at {company}
Job description excerpt: {description}

Candidate profile:
- Name: {profile['full_name']}
- Current role: {profile['current_title']} at {profile['current_company']}
- Education: {profile['highest_education']}
- Key skills: {', '.join(profile.get('skills', [])[:8])}
- Location: Melbourne, VIC, Australia
- Experience: {profile.get('years_experience', 4)} years

Instructions:
- Address to "Hiring Team" (no specific name)
- Paragraph 1: Express interest, mention the role and company
- Paragraph 2: 2-3 specific skills/achievements matching the JD
- Paragraph 3: Enthusiasm + call to action
- Sign off: "Kind regards, {profile['full_name']}"
- Professional, not generic — reference actual JD keywords
- Do NOT include address headers or date"""

    result = _call_ai(prompt)
    if not result:
        # Fallback template
        result = (
            f"Dear Hiring Team,\n\n"
            f"I am writing to express my strong interest in the {title} position at {company}. "
            f"With my background in {profile.get('current_title', 'IT and analytics')} and a "
            f"{profile.get('highest_education', 'Master of Business Analytics')}, I am well-positioned "
            f"to contribute meaningfully to your team.\n\n"
            f"My experience includes {', '.join(profile.get('skills', [])[:4])}, which I believe "
            f"directly aligns with the requirements of this role. I am particularly drawn to this "
            f"opportunity due to its focus on technology consulting and digital transformation.\n\n"
            f"I would welcome the opportunity to discuss how my skills and experience can contribute "
            f"to your organisation. Thank you for your consideration.\n\n"
            f"Kind regards,\n{profile['full_name']}"
        )
    return result


def extract_keywords(job_description: str) -> list:
    """Extract key skills/requirements from a job description."""
    if not job_description:
        return []

    prompt = f"""Extract the top 10 technical skills and requirements from this job description.
Return as a JSON array of strings only, no explanation.

Job description:
{job_description[:1500]}

Example output: ["Python", "SQL", "Power BI", "Azure", "Agile"]"""

    result = _call_ai(prompt)
    try:
        # Extract JSON array
        match = re.search(r'\[.*?\]', result, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception:
        pass

    # Fallback: split by comma
    cleaned = re.sub(r'[\[\]"\n]', '', result)
    return [k.strip() for k in cleaned.split(',') if k.strip()][:10]


if __name__ == "__main__":
    test_job = {
        "title": "Data Analyst",
        "company": "Thoughtworks Australia",
        "description": (
            "We are looking for a Data Analyst with strong SQL, Python, and Power BI skills. "
            "You will work with clients in financial services to build dashboards and insights. "
            "Experience with Azure and Microsoft stack preferred. Agile environment."
        ),
    }
    print("=== Cover Letter ===")
    cl = generate_cover_letter(test_job)
    print(cl)
    print("\n=== Keywords ===")
    kw = extract_keywords(test_job["description"])
    print(kw)
