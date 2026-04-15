# Microsoft Redeem Code Finder

A sleek web app for Singapore-based Microsoft Certified Trainers (MCTs) to look up Microsoft Learn courses from the official Title Plan, open the correctly-tracked Singapore course page, and generate achievement codes end-to-end via Playwright.

**Live demo (search + SG links only):** https://alfredang.github.io/microsoftredeemcode/

> Code generation requires running the Python backend locally — GitHub Pages can only serve the static search UI.

---

## What it does

1. **Search** the 132-course April 2026 Title Plan by course number or title.
2. **Open Singapore course page** with the correct partner tracking appended:
   `?WT.mc_id=ilt_partner_webpage_wwl&ocid=5238477`.
3. **Generate achievement codes** (locally only) — Playwright drives Chromium through the Microsoft Learn flow:
   1. Finds and clicks *Request achievement code* anywhere on the course page.
   2. Enters the number of students into the modal.
   3. Clicks *Request code*.
   4. Extracts the code + redemption URL, appends to `data/codes.csv`, and shows them in the UI.

---

## Quick start

### Static mode (search + SG links only)

Just open https://alfredang.github.io/microsoftredeemcode/ — no install required.

### Full mode (with code generation)

```bash
git clone https://github.com/alfredang/microsoftredeemcode.git
cd microsoftredeemcode/webapp

# Install Python deps
python -m pip install flask playwright
python -m playwright install chromium

# Start the app
python server.py
```

Open http://localhost:8000.

---

## Code generation

### One-time: sign in to Microsoft Learn

Click **Sign in to Microsoft** in the auth bar at the top of the page. A Chromium window opens — sign in with your MCT account, then either click the injected **Finish & save session** banner or close the window. Playwright writes your session to `webapp/data/storage_state.json` and reuses it silently for subsequent generations.

> ⚠️ `storage_state.json` contains live Microsoft auth cookies. It is in `.gitignore` — never commit it.

### Generating a code

1. Search for a course.
2. On the matching card, set **Number of students**.
3. Click **Generate achievement code**.

The code + URL render inline on the card, appended to `data/codes.csv` as:

```csv
timestamp,courseNumber,code,url,students
2026-04-15T02:34:12+00:00,AI-102T00,8X582M,https://learn.microsoft.com/...,25
```

If a step fails, a screenshot + full page HTML dump land in `data/debug/` and the UI shows a step-labeled error (e.g. `Find Request achievement code button: …`).

---

## Updating the Title Plan

When a new `titleplan_*.xlsx` drops:

1. Replace the xlsx at the repo root.
2. Update the path in `webapp/extract_courses.py` if the filename changed.
3. Regenerate the JSON: `python webapp/extract_courses.py`.
4. Commit `courses.json` alongside the xlsx.

---

## Project layout

```
microsoftredeemcode/
├── .github/workflows/pages.yml   # deploys webapp/ to GitHub Pages
├── titleplan_april10_2026.xlsx   # source of truth
├── webapp/
│   ├── index.html · styles.css · app.js   # static UI
│   ├── courses.json              # extracted from xlsx
│   ├── extract_courses.py        # xlsx → json
│   ├── server.py                 # Flask app: static + /api/*
│   └── backend/
│       ├── login.py              # Playwright sign-in flow
│       ├── generate.py           # Playwright code-generation flow
│       └── paths.py              # shared paths + Singapore URL suffix
└── README.md
```

---

## Tech stack

- **Frontend:** plain HTML/CSS/JS, no build step.
- **Backend:** Flask (static serving + thin JSON API).
- **Automation:** Playwright (Python), Chromium.
- **Data source:** Microsoft MCT Courseware Title Plan (Excel).

---

## Security notes

- `storage_state.json` (MS auth cookies) and `codes.csv` (generated codes) are gitignored.
- The Flask server binds to `127.0.0.1` only — it is not exposed to the network.
- Never commit the `data/` folder contents.

---

## License

Internal partner tooling. Not affiliated with or endorsed by Microsoft.
