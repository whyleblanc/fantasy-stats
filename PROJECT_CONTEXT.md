# Fantasy Basketball Analytics Dashboard – Project Context (Updated vNext)

## Overview
A full-stack analytics platform for ESPN H2H 9-category fantasy basketball.

Backend: Flask + Python + espn_api + SQLite/SQLAlchemy  
Frontend: React (Vite) SPA  
Goal: Provide multi-year league intelligence, weekly matchup insights, and team performance analytics with interactive visualizations.

---

## Key Features

### Core Stats
- Season-long and weekly z-scores  
- Weekly and season-long power rankings  
- Category-level breakdowns  
- Luck index and fraud index  
- Opponent strength metrics  
- League metadata (owners, standings, PF/PA, final rank)

### Team History (Refactored)
- Year selector → Team selector  
- Week-by-week performance tracking  
- Three chart modes:
  1. Weekly Total Z  
  2. Weekly Rank (1 = best)  
  3. Category Z-score  
- Comparison Team Mode (overlay another team on all chart modes)  
- Week Range Slider (filter charts dynamically)  
- League average overlays  
- Best week, worst week, average rank summary cards  
- Full weekly category Z-score table

### Dashboard
- Weekly power tables  
- Category standings  
- Per-team breakdowns  
- Fewer dropdowns, centralized control panel  
- Selectors for year, week, team, category

### Overview
- League standings  
- Season summaries  
- High-level metrics  

---

## Backend Endpoints

### Metadata
`/api/meta`  
Returns years, weeks, currentWeek, leagueName, teamCount.

### League
`/api/league`  
Returns team records, owners, PF/PA, final standings.

### Analysis
`/api/analysis/week-zscores`  
`/api/analysis/season-zscores`  
`/api/analysis/week-power`  
`/api/analysis/season-power`  
`/api/analysis/team-history`

### Debug
`/api/debug/week-raw`  
`/api/debug/week-cats`

---

## Architecture

### Backend (Python)
- **app.py** — Flask routing, metadata handling, owner mapping, safety wrappers, CORS  
- **analysis.py** — all computation logic: z-scores, power rankings, luck/fraud, history  
- **db.py** — SQLAlchemy model for WeekTeamStats  
- **helpers:** derive_current_week, league payload builders, owners extractors

### Frontend (React + Vite)
- **src/App.jsx** — main UI shell, global selectors, routing between tabs  
- **src/components/**  
  - OverviewTab  
  - DashboardTab  
  - HistoryTab (major refactor completed)  
  - Chart utilities, table components, theme/UI modules  
- **src/api/**  
  - client.js (fetch wrapper)  
  - endpoints for meta, league, history, week/season analyses  

---

## Setup

### Backend
- python -m venv .venv
- source .venv/bin/activate
- pip install -r requirements.txt
- python app.py  # runs on port 5001

### Frontend Setup
- cd frontend
- npm install
- npm run dev  # runs on 5173

### Environment Variables (.env)
LEAGUE_ID=70600
SWID={YOUR_SWID}
ESPN_S2={YOUR_ESPN_S2}

---

## Current Tasks (Next Steps)

1. **Finish HistoryTab polish**
   - Comparison line coloring  
   - Minor UX cleanup  

2. **Backend refactor (optional but recommended)**
   - `/webapp/` for Flask  
   - `/services/` for ESPN + analysis  
   - `/models/`, `/config/`, `/routes/`  
   - Serve frontend static build in production

3. **Awards Tab**
   - Historical champions  
   - Best/worst season, week, categories  
   - Lucky/unlucky summaries  

4. **Sortable Tables**
   - Click-to-sort on all tables  

5. **Stability improvements**
   - Error boundaries in React  
   - Resilient ESPN fallback logic  
   - UI cache invalidation controls  

6. **Deployment Prep**
   - Production build pipeline  
   - Serve Vite build via Flask  
   - Optional: Nginx reverse proxy  
   - GitHub CI/CD  

---

## Summary
The project now has:
- A stable backend analysis engine  
- A modern interactive frontend  
- A fully rebuilt HistoryTab with multi-mode charts, comparison mode, category tracking, and dynamic week filtering  
- A consistent architecture ready for future expansion (Awards tab, sortable tables, deployment)

This file is the canonical context for all future development.