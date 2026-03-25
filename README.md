# Consulting Applier — Type A Automation

Full automation pipeline for Melbourne consulting firms.
Scrapes Lever / Workday / Greenhouse → stores in Supabase → Telegram cards → you approve → Playwright applies.

## Project structure

```
consulting_applier/
├── firms.json                    ← Target firm database (20 firms)
├── requirements.txt
├── scraper/
│   ├── lever_scraper.py          ← Lever public API
│   ├── workday_scraper.py        ← Workday CXS API
│   ├── greenhouse_scraper.py     ← Greenhouse boards API
│   └── scraper_router.py         ← Reads firms.json, routes to correct scraper
├── db/
│   └── supabase_client.py        ← Upsert, update status, migration
├── bot/
│   └── telegram_notifier.py      ← Send job cards with inline buttons
├── orchestrator/
│   └── daily_runner.py           ← Main cron entry point
├── applier/                      ← (Week 2) Playwright form fillers
├── ai/                           ← (Week 2) Resume tailoring per JD
└── logs/
```

## Setup on VPS

### 1. Copy to VPS
```bash
scp -r consulting_applier/ rachit@<VPS_IP>:/home/rachit/.openclaw/workspace/
```

### 2. Install dependencies
```bash
cd /home/rachit/.openclaw/workspace/consulting_applier
pip3 install -r requirements.txt --break-system-packages
playwright install chromium --with-deps
```

### 3. Run DB migration
```bash
python3 db/supabase_client.py
```

### 4. Test scrapers (dry run — no DB, no Telegram)
```bash
# Test all ATS types
python3 orchestrator/daily_runner.py --dry-run

# Test only Lever firms
python3 orchestrator/daily_runner.py --ats lever --dry-run

# Test individual scraper
python3 scraper/lever_scraper.py
python3 scraper/greenhouse_scraper.py
python3 scraper/workday_scraper.py
```

### 5. Test Telegram notification
```bash
python3 bot/telegram_notifier.py
```

### 6. Full run (scrape + store + notify)
```bash
python3 orchestrator/daily_runner.py
```

### 7. Add to crontab
```bash
crontab -e
```
Add this line (runs at 6 AM Melbourne time):
```
0 6 * * * cd /home/rachit/.openclaw/workspace/consulting_applier && python3 orchestrator/daily_runner.py >> logs/runner.log 2>&1
```

## firms.json — firms by ATS type

| ATS | Firms |
|-----|-------|
| Workday | Deloitte, PwC, Accenture, Wipro, Kyndryl, DXC, Cognizant, Avanade |
| Lever | KPMG, Thoughtworks, Versent, Mantel Group |
| Greenhouse | EY, Capgemini, Atturra, NCS Australia |
| Custom (TODO) | Infosys, TCS, BizData, Data#3 |

## What's built (Week 1)

- [x] firms.json — 20 firms mapped
- [x] Lever scraper
- [x] Workday scraper
- [x] Greenhouse scraper
- [x] Scraper router
- [x] Supabase client + migration
- [x] Telegram job card notifier
- [x] Daily runner (cron entry point)

## What's next (Week 2)

- [ ] bot/bot_server.py — FastAPI webhook to handle approve/skip callbacks
- [ ] applier/apply_lever.py — Playwright Lever form filler
- [ ] applier/apply_greenhouse.py
- [ ] applier/apply_workday.py
- [ ] ai/tailor_resume.py — JD-matched resume per application
- [ ] candidate_profile.json — your details for form autofill


## Streamlit Cloud deployment

This repository now includes a Streamlit entrypoint (`streamlit_app.py`) so it can be deployed on [streamlit.app](https://streamlit.app).

1. In Streamlit Community Cloud, point your app to this repo/branch.
2. Set the main file path to `streamlit_app.py`.
3. Add secrets/environment variables as needed (for APIs used by your scrapers).
4. Deploy.

Local run:
```bash
streamlit run streamlit_app.py
```



### Added supplier APIs in Streamlit

The Streamlit app now supports all requested supplier feeds in one place:
- Adzuna (`api.adzuna.com`)
- Careerjet (`public.api.careerjet.net/search`)
- Seek (`seek.com.au/api/jobsearch/v5/search`)
- JSearch (`jsearch.p.rapidapi.com/search`)

Optional: send fetched supplier jobs to your processor endpoint (default: `http://localhost:5680`).

Supabase is now also supported in the Streamlit supplier flow: enable **Also save results to Supabase** to upsert supplier jobs into the existing `job_applications` table using `supabase_client.upsert_job`.

Environment variables used by supplier fetchers:
- `ADZUNA_APP_ID`
- `ADZUNA_APP_KEY`
- `CAREERJET_AFFID`
- `RAPIDAPI_KEY`

