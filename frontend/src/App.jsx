// src/App.jsx
import { useEffect, useMemo, useState } from "react";
import "./App.css";

import OverviewTab from "./components/OverviewTab";
import DashboardTab from "./components/DashboardTab";
import HistoryTab from "./components/HistoryTab";

import {
  getMeta,
  getLeague,
  getWeekPower,
  getSeasonPower,
  getTeamHistory,
} from "./api/client";

// Central categories list
const CATEGORIES = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"];

function App() {
  // ---- nav ----
  const [tab, setTab] = useState("overview"); // 'overview' | 'dashboard' | 'history'

  // ---- meta + filters ----
  const [meta, setMeta] = useState({
    years: [],
    weeks: [],
    year: 2025,
    currentWeek: null,
    leagueName: "",
    teamCount: 0,
  });

  const [year, setYear] = useState(2025);
  const [week, setWeek] = useState(1);

  // ---- data ----
  const [weekPower, setWeekPower] = useState(null);
  const [seasonPower, setSeasonPower] = useState(null);
  const [standingsLeague, setStandingsLeague] = useState(null);

  // ---- history view ----
  const [historyTeamId, setHistoryTeamId] = useState(null);
  const [historyData, setHistoryData] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // ---- loading / error ----
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [loadingWeek, setLoadingWeek] = useState(false);
  const [loadingSeason, setLoadingSeason] = useState(false);
  const [loadingLeague, setLoadingLeague] = useState(false);
  const [error, setError] = useState(null);

  // Latest season for ESPN standings
  const standingsYear = useMemo(() => {
    if (meta.years && meta.years.length > 0) {
      return Math.max(...meta.years);
    }
    return year;
  }, [meta.years, year]);

  // ---- API helpers ----

  const fetchMeta = async (y) => {
    setLoadingMeta(true);
    setError(null);
    try {
      const data = await getMeta(y);
      setMeta(data);
      return data;
    } catch (e) {
      console.error(e);
      setError(e.message);
      return null;
    } finally {
      setLoadingMeta(false);
    }
  };

  const fetchWeekPowerData = async (y, w) => {
    if (!y || !w) return;
    setLoadingWeek(true);
    setError(null);
    try {
      const data = await getWeekPower(y, w);
      setWeekPower(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Week power error");
      setWeekPower(null);
    } finally {
      setLoadingWeek(false);
    }
  };

  const fetchSeasonPowerData = async (y) => {
    if (!y) return;
    setLoadingSeason(true);
    setError(null);
    try {
      const data = await getSeasonPower(y);
      setSeasonPower(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Season power error");
      setSeasonPower(null);
    } finally {
      setLoadingSeason(false);
    }
  };

  const fetchLeagueStandings = async (y) => {
    if (!y) return;
    setLoadingLeague(true);
    setError(null);
    try {
      const data = await getLeague(y);
      setStandingsLeague(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "League error");
      setStandingsLeague(null);
    } finally {
      setLoadingLeague(false);
    }
  };

  const fetchHistoryData = async (y, teamId) => {
    if (!y || !teamId) return;
    setLoadingHistory(true);
    setError(null);
    try {
      const data = await getTeamHistory(y, teamId);
      setHistoryData(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Team history error");
      setHistoryData(null);
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleRefresh = () => {
    if (year && week) fetchWeekPowerData(year, week);
    if (year) fetchSeasonPowerData(year);
    if (standingsYear) fetchLeagueStandings(standingsYear);
    if (tab === "history" && historyTeamId && year) {
      fetchHistoryData(year, historyTeamId);
    }
  };

  // ---- effects ----

  // First load: meta for default season
  useEffect(() => {
    const bootstrap = async () => {
      const data = await fetchMeta();
      if (!data) return;

      const y = data.year;
      if (y) setYear(y);

      const weeks = data.weeks || [];
      if (!weeks.length) return;

      const defaultWeek =
        data.currentWeek && weeks.includes(data.currentWeek)
          ? data.currentWeek
          : weeks[weeks.length - 1];

      setWeek(defaultWeek);

      fetchWeekPowerData(y, defaultWeek);
      fetchSeasonPowerData(y);
    };

    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When year changes: refresh meta + season + week (clamp week)
  useEffect(() => {
    if (!year) return;
    const loadYear = async () => {
      const data = await fetchMeta(year);
      if (!data) return;

      const weeks = data.weeks || [];
      if (!weeks.length) return;

      let w = week;
      if (!w || !weeks.includes(w)) {
        w =
          data.currentWeek && weeks.includes(data.currentWeek)
            ? data.currentWeek
            : weeks[weeks.length - 1];
        setWeek(w);
      }

      fetchWeekPowerData(year, w);
      fetchSeasonPowerData(year);
    };
    loadYear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year]);

  // ESPN standings: always latest season (standingsYear)
  useEffect(() => {
    if (!standingsYear) return;
    fetchLeagueStandings(standingsYear);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standingsYear]);

  // Auto-select default team when opening Team History
  useEffect(() => {
    if (tab !== "history") return;
    if (historyTeamId) return;

    const teams = seasonPower?.teams || [];
    if (!teams.length) return;

    const sorted = [...teams].sort(
      (a, b) => (a.rank ?? 999) - (b.rank ?? 999)
    );
    const first = sorted[0];
    if (first && first.teamId) {
      setHistoryTeamId(first.teamId);
    }
  }, [tab, seasonPower, historyTeamId]);

  // Fetch history when tab/year/team changes
  useEffect(() => {
    if (tab !== "history") return;
    if (!historyTeamId || !year) return;
    fetchHistoryData(year, historyTeamId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, year, historyTeamId]);

  // ---- UI helpers ----

  const handleHistoryTeamChange = (teamId) => {
    setHistoryTeamId(teamId);
  };

  const renderTabs = () => (
    <div
      style={{
        display: "flex",
        gap: "8px",
        marginBottom: "16px",
        borderBottom: "1px solid #1f2937",
      }}
    >
      {[
        { id: "overview", label: "Overview" },
        { id: "dashboard", label: "Dashboard" },
        { id: "history", label: "Team History" },
      ].map((t) => {
        const active = tab === t.id;
        return (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              border: "none",
              borderBottom: active
                ? "2px solid #38bdf8"
                : "2px solid transparent",
              background: "transparent",
              color: active ? "#e5e7eb" : "#9ca3af",
              padding: "8px 12px",
              cursor: "pointer",
              fontWeight: active ? 600 : 500,
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );

  const renderFilterStrip = () => (
    <section
      style={{
        marginBottom: "16px",
        display: "flex",
        flexWrap: "wrap",
        gap: "12px",
        alignItems: "center",
      }}
    >
      <div>
        <label style={{ fontSize: "0.9rem" }}>Year</label>
        <select
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          style={{
            display: "block",
            marginTop: "4px",
            padding: "4px 8px",
            borderRadius: "6px",
            border: "1px solid #334155",
            background: "#020617",
            color: "#e5e7eb",
            minWidth: "120px",
          }}
        >
          {meta.years?.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label style={{ fontSize: "0.9rem" }}>Week</label>
        <select
          value={week}
          onChange={(e) => setWeek(Number(e.target.value))}
          style={{
            display: "block",
            marginTop: "4px",
            padding: "4px 8px",
            borderRadius: "6px",
            border: "1px solid #334155",
            background: "#020617",
            color: "#e5e7eb",
            minWidth: "90px",
          }}
        >
          {meta.weeks?.map((w) => (
            <option key={w} value={w}>
              {w}
            </option>
          ))}
        </select>
      </div>

      <button
        onClick={handleRefresh}
        style={{
          marginTop: "18px",
          padding: "6px 16px",
          borderRadius: "999px",
          border: "none",
          background:
            "linear-gradient(135deg, rgba(56,189,248,0.9), rgba(59,130,246,0.9))",
          color: "#0f172a",
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        Refresh
      </button>

      {error && (
        <span style={{ color: "#fca5a5", fontSize: "0.85rem" }}>
          {error}
        </span>
      )}
    </section>
  );

  // ---- render root ----
  return (
    <div
      style={{
        minHeight: "100vh",
        fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
        padding: "16px",
        background: "#0f172a",
        color: "#e5e7eb",
      }}
    >
      <header style={{ marginBottom: "16px" }}>
        <h1 style={{ margin: 0, fontSize: "1.8rem" }}>
          {meta.leagueName || "Fantasy Power Dashboard"}
        </h1>
        <p style={{ margin: "4px 0 0", color: "#94a3b8" }}>
          ESPN League {year} · Week {week}
          {meta.currentWeek && meta.currentWeek !== week && (
            <span
              style={{ marginLeft: 8, fontSize: "0.8rem", color: "#64748b" }}
            >
              (Current matchup week: {meta.currentWeek})
            </span>
          )}
        </p>
      </header>

      {renderTabs()}
      {renderFilterStrip()}

      {loadingMeta && <div>Loading league metadata…</div>}

      {!loadingMeta && tab === "overview" && (
        <OverviewTab
          year={year}
          week={week}
          standingsYear={standingsYear}
          weekPower={weekPower}
          seasonPower={seasonPower}
          leagueInfo={standingsLeague}
          loadingWeek={loadingWeek}
          loadingSeason={loadingSeason}
          loadingLeague={loadingLeague}
          categories={CATEGORIES}
        />
      )}

      {!loadingMeta && tab === "dashboard" && (
        <DashboardTab
          year={year}
          week={week}
          weekPower={weekPower}
          seasonPower={seasonPower}
          loadingWeek={loadingWeek}
          loadingSeason={loadingSeason}
          categories={CATEGORIES}
        />
      )}

      {!loadingMeta && tab === "history" && (
        <HistoryTab
          year={year}
          seasonPower={seasonPower}
          historyData={historyData}
          loadingHistory={loadingHistory}
          selectedTeamId={historyTeamId}
          onChangeTeam={handleHistoryTeamChange}
          categories={CATEGORIES}
        />
      )}
    </div>
  );
}

export default App;