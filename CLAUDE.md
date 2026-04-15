# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A web app for Singapore MCTs to search Microsoft Learn courses from the Title Plan, open Singapore-tracked course pages, and generate achievement codes via Playwright browser automation. The static search UI is deployed to GitHub Pages; code generation requires the local Flask backend.

## Commands

```bash
# Install dependencies
python -m pip install flask playwright openpyxl
python -m playwright install chromium

# Run the server (serves UI + API on http://localhost:8000)
cd webapp && python server.py

# Regenerate courses.json from a new Title Plan xlsx
python webapp/extract_courses.py
```

## Architecture

**Two-mode deployment:**
- **Static mode** (GitHub Pages): `webapp/` served as-is — search + Singapore links only, no backend
- **Full mode** (local Flask): `webapp/server.py` serves static files AND exposes `/api/*` endpoints that drive Playwright

**Backend flow (Playwright automation):**
1. `POST /api/login` → `backend/login.py` opens headed Chromium for MCT sign-in, saves session to `data/storage_state.json`
2. `POST /api/generate` → `backend/generate.py` uses saved session in headless Chromium to navigate course page, click "Request achievement code", fill student count, extract generated code + URL, append to `data/codes.csv`
3. On failure, screenshots + HTML dumps go to `data/debug/`

**Key modules:**
- `backend/paths.py` — shared paths (`ROOT`, `DATA`, `STORAGE_STATE`, `CODES_CSV`) and the Singapore tracking suffix (`SG_SUFFIX`)
- `backend/generate.py` — multi-strategy button/modal finding (role, text, clickable selectors across frames), `StepError` for step-labeled failures
- `backend/login.py` — polls for auth cookies (`ESTSAUTH*`) or injected "Finish" button click, 10-min timeout
- `extract_courses.py` — reads xlsx column layout (solution area, course number, title, duration, credential, detail URL) into `courses.json`

**Frontend:** Plain HTML/CSS/JS with no build step. `courses.json` is fetched client-side for search.

## Data Files (gitignored)

- `webapp/data/storage_state.json` — Microsoft auth cookies (sensitive)
- `webapp/data/codes.csv` — generated achievement codes
- `webapp/data/debug/` — failure screenshots and HTML dumps

## Updating the Title Plan

Replace the xlsx at repo root, update the path in `extract_courses.py` if filename changed, run `python webapp/extract_courses.py`, commit `courses.json` alongside the xlsx.
