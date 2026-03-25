#!/usr/bin/env python3
"""Streamlit UI for ATS scrapers + public job suppliers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from job_suppliers import post_to_jobprocessor, run_supplier_search, save_jobs_to_supabase
from scraper_router import run_all_scrapers

st.set_page_config(page_title="Consulting Applier", page_icon="💼", layout="wide")
st.title("💼 Consulting Applier")
st.caption("Streamlit-compatible UI for firm ATS scraping and supplier APIs (Adzuna, Careerjet, Seek, JSearch).")

ats_tab, supplier_tab = st.tabs(["Firm ATS Scrapers", "Job Supplier APIs"])

with ats_tab:
    with st.sidebar:
        st.header("ATS run options")
        ats_options = ["lever", "workday", "greenhouse"]
        selected_ats = st.multiselect("ATS filters", options=ats_options, default=ats_options)
        max_rows = st.slider("Preview rows", min_value=10, max_value=500, value=100, step=10)
        run_ats = st.button("Run ATS scrape", type="primary")

    if run_ats:
        with st.spinner("Running ATS scrapers..."):
            jobs = run_all_scrapers(ats_filter=selected_ats or None)

        st.success(f"Found {len(jobs)} jobs")
        if jobs:
            df = pd.DataFrame(jobs).head(max_rows)
            st.dataframe(df, use_container_width=True)
            st.download_button("Download ATS CSV", data=df.to_csv(index=False).encode("utf-8"), file_name="ats_jobs.csv")
        else:
            st.info("No ATS jobs found for the selected filters.")
    else:
        st.info("Use the sidebar and click **Run ATS scrape**.")

with supplier_tab:
    st.subheader("Run public job supplier search")
    col1, col2 = st.columns(2)
    with col1:
        keyword = st.text_input("Keywords", value="systems analyst")
    with col2:
        where = st.text_input("Location", value="Melbourne")

    suppliers = st.multiselect(
        "Suppliers",
        options=["adzuna", "careerjet", "seek", "jsearch"],
        default=["adzuna", "careerjet", "seek", "jsearch"],
        help="Runs all selected providers in one click.",
    )

    post_enabled = st.checkbox("Also POST results to jobprocessor", value=False)
    save_supabase = st.checkbox("Also save results to Supabase", value=False)
    endpoint = st.text_input("jobprocessor endpoint", value="http://localhost:5680")

    if st.button("Run supplier search", type="primary"):
        with st.spinner("Fetching supplier results..."):
            jobs = run_supplier_search(what=keyword, where=where, suppliers=suppliers)

        st.success(f"Fetched {len(jobs)} jobs from {', '.join(suppliers)}")
        if jobs:
            df = pd.DataFrame(jobs)
            st.dataframe(df[[c for c in ["source", "title", "company", "location", "apply_url"] if c in df.columns]], use_container_width=True)
            st.download_button("Download Supplier CSV", data=df.to_csv(index=False).encode("utf-8"), file_name="supplier_jobs.csv")

            if save_supabase:
                stats = save_jobs_to_supabase(jobs)
                st.info(f"Supabase upsert: {stats['inserted']} inserted, {stats['skipped']} skipped (total {stats['total']}).")

            if post_enabled:
                result = post_to_jobprocessor(jobs, endpoint=endpoint)
                if result.get("ok"):
                    st.success(f"Posted to {endpoint} (status {result.get('status_code')})")
                else:
                    st.error(f"POST failed: {result}")
        else:
            st.warning("No supplier jobs were returned. Check API keys / rate limits.")
