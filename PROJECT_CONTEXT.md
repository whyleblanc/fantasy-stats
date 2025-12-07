# Fantasy Basketball Analytics Dashboard – Context Loadout

## Overview
A full-stack analytics platform for ESPN H2H 9-category fantasy basketball.
Backend: Flask + Python + espn_api + SQLAlchemy
Frontend: React SPA (App.jsx)

## Key Features
• Season & weekly z-scores  
• Weekly & season-long power rankings  
• All-play expected wins  
• Luck index and fraud index  
• Team history cumulative charts  
• Owners, standings, league metadata  
• Heatmap + dashboard views  

## Backend Endpoints
/api/meta  
/api/league  
/api/analysis/week-zscores  
/api/analysis/season-zscores  
/api/analysis/week-power  
/api/analysis/season-power  
/api/analysis/team-history  

## Architecture
- app.py: Flask router + metadata + league payloads  
- analysis.py: all calculations (z-scores, power, luck, fraud, history)  
- db.py: SQLAlchemy model for WeekTeamStats (ignored in repo)  
- frontend/src/App.jsx: main UI logic  

## Setup
- Python venv  
- flask run --port 5001  
- React dev server on :5173  
- .env contains ESPN creds  

## Current Tasks
- UI revamp: new tabs (Overview / Dashboard / History / Awards)  
- Dashboard: graphs, filters, year/week/team/category selectors  
- Awards tab: historical champions, standings, best/worst z-score metrics  
- History tab: per-season team summary, best/worst finishes  
- Sorting: make all tables sortable by clicking column headers  
- ESPN standings integration  