#!/usr/bin/env python3
"""Streamlit UI for running and previewing job scrapes."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from scraper_router import run_all_scrapers

st.set_page_config(page_title="Consulting Applier", page_icon="💼", layout="wide")
st.title("💼 Consulting Applier")
st.caption("Streamlit-compatible interface for running ATS scrapers and previewing jobs.")

with st.sidebar:
    st.header("Run options")
    ats_options = ["lever", "workday", "greenhouse"]
    selected_ats = st.multiselect("ATS filters", options=ats_options, default=ats_options)
    max_rows = st.slider("Preview rows", min_value=10, max_value=500, value=100, step=10)
    run_clicked = st.button("Run scrape", type="primary")

if run_clicked:
    with st.spinner("Running scrapers..."):
        jobs = run_all_scrapers(ats_filter=selected_ats or None)

    st.success(f"Found {len(jobs)} jobs")

    if not jobs:
        st.info("No jobs found for the selected filters.")
    else:
        df = pd.DataFrame(jobs)
        preview = df.head(max_rows)
        st.dataframe(preview, use_container_width=True)

        csv_data = preview.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download preview as CSV",
            data=csv_data,
            file_name="jobs_preview.csv",
            mime="text/csv",
        )

        required_cols = [
            c for c in ["title", "company", "location", "ats_type", "apply_url"] if c in preview.columns
        ]
        if required_cols:
            st.subheader("Quick view")
            st.table(preview[required_cols].fillna(""))
else:
    st.info("Choose filters in the sidebar, then click **Run scrape**.")
