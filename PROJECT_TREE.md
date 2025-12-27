.
├── GPT_ANALYTICS_NOTES.md
├── GPT_API_CONTRACTS.md
├── GPT_KNOWLEDGE_BUNDLE.zip
├── GPT_PROJECT_CONTEXT.md
├── GPT_PROJECT_TREE.md
├── PROJECT_CONTEXT.md
├── PROJECT_TREE.md
├── README.md
├── analysis
│   ├── __init__.py
│   ├── constants.py
│   ├── loaders.py
│   ├── metrics.py
│   ├── models.py
│   ├── owners.py
│   └── services.py
├── app.py
├── db.py
├── docs
│   └── gpt
│       ├── CHANGELOG_DEV.md
│       ├── GPT_INSTRUCTIONS.md
│       ├── PROJECT_INSTRUCTIONS.md
│       ├── README.md
│       └── RUNBOOK.md
├── fantasy_stats.db
├── frontend
│   ├── README.md
│   ├── eslint.config.js
│   ├── index.html
│   ├── package-lock.json
│   ├── package.json
│   ├── public
│   │   └── vite.svg
│   ├── src
│   │   ├── App.css
│   │   ├── App.jsx
│   │   ├── api
│   │   │   └── client.js
│   │   ├── assets
│   │   │   └── react.svg
│   │   ├── components
│   │   │   ├── DashboardTab.jsx
│   │   │   ├── ErrorBoundary.jsx
│   │   │   ├── HistoryChart.jsx
│   │   │   ├── HistoryControls.jsx
│   │   │   ├── HistoryHeader.jsx
│   │   │   ├── HistorySummary.jsx
│   │   │   ├── HistoryTab.jsx
│   │   │   ├── HistoryTable.jsx
│   │   │   ├── OpponentAnalysisTab.jsx
│   │   │   ├── OverviewTab.jsx
│   │   │   └── SortHeader.jsx
│   │   ├── espn_helpers.py
│   │   ├── index.css
│   │   ├── main.jsx
│   │   └── ui
│   │       └── table.jsx
│   └── vite.config.js
├── gpt_knowledge_bundle
│   ├── GPT_ANALYTICS_NOTES.md
│   ├── GPT_API_CONTRACTS.md
│   ├── GPT_PROJECT_CONTEXT.md
│   ├── GPT_PROJECT_TREE.md
│   └── README.md
├── models_aggregates.py
├── models_normalized.py
├── pytest.ini
├── requirements.txt
├── scripts
│   ├── __init__.py
│   ├── backfill_history.py
│   ├── backfill_team_weekly.py
│   ├── backfill_weekly_from_boxscores.py
│   ├── backfill_weekteamstats.py
│   ├── correct_recent_weeks.py
│   ├── inspect_espn_week_payload.py
│   ├── print_owners_2025.py
│   ├── pull_latest.sh
│   ├── pull_latest_week.py
│   ├── pull_week.py
│   ├── rebuild_opponent_matrix_agg_year.py
│   ├── rebuild_team_history_agg_year.py
│   ├── temp_shell.py
│   └── update_project_tree.sh
├── tests
│   ├── conftest.py
│   ├── contest.py
│   ├── test_meta_completed_weeks.py
│   └── test_opponent_matrix_multi.py
└── webapp
    ├── __init__.py
    ├── config.py
    ├── legacy_services.py
    ├── routes
    │   ├── __init__.py
    │   ├── analysis.py
    │   ├── debug.py
    │   ├── league.py
    │   ├── legacy.py
    │   └── meta.py
    └── services
        ├── __init__.py
        ├── analytics_engine.py
        ├── cache_week_team_stats.py
        ├── espn_ingest.py
        ├── loaders.py
        ├── opponent_matrix_agg.py
        ├── opponent_matrix_agg_year.py
        ├── opponent_matrix_db.py
        ├── standings_cache.py
        └── team_history_agg.py

17 directories, 96 files
