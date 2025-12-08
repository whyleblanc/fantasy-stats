// src/App.jsx
import { useEffect, useMemo, useState } from "react";
import "./App.css";

import OverviewTab from "./components/OverviewTab";
import DashboardTab from "./components/DashboardTab";
import HistoryTab from "./components/HistoryTab";
import { api } from "./api/client";

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
  const [leagueInfo, setLeagueInfo] = useState(null);

  // team history
  const [selectedTeamId, setSelectedTeamId] = useState(null);
  const [teamHistory, setTeamHistory] = useState(null);

  // ---- loading / error ----
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [loadingWeek, setLoadingWeek] = useState(false);
  const [loadingSeason, setLoadingSeason] = useState(false);
  const [loadingLeague, setLoadingLeague] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState(null);

  // Latest season for ESPN standings (always current)
  const standingsYear = useMemo(() => {
    if (meta.years && meta.years.length > 0) {
      return Math.max(...meta.years);
    }
    return year;
  }, [meta.years, year]);

  // Teams available for the selected year, for history dropdown
  const teamsForYear = useMemo(() => {
    const teams = seasonPower?.teams || weekPower?.teams || [];
    return teams.filter((t) => t.teamId && t.teamId !== 0);
  }, [seasonPower, weekPower]);

  // ---- API helpers (using api/client.js) ----

  const fetchMeta = async (y) => {
    setLoadingMeta(true);
    setError(null);
    try {
      const data = await api.getMeta(y);
      setMeta(data);
      return data;
    } catch (e) {
      console.error(e);
      setError(e.message || "Meta error");
      return null;
    } finally {
      setLoadingMeta(false);
    }
  };

  const fetchWeekPower = async (y, w) => {
    if (!y || !w) return;
    setLoadingWeek(true);
    setError(null);
    try {
      const data = await api.getWeekPower(y, w);
      setWeekPower(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Week power error");
      setWeekPower(null);
    } finally {
      setLoadingWeek(false);
    }
  };

  const fetchSeasonPower = async (y) => {
    if (!y) return;
    setLoadingSeason(true);
    setError(null);
    try {
      const data = await api.getSeasonPower(y);
      setSeasonPower(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Season power error");
      setSeasonPower(null);
    } finally {
      setLoadingSeason(false);
    }
  };

  const fetchLeague = async (y) => {
    if (!y) return;
    setLoadingLeague(true);
    setError(null);
    try {
      const data = await api.getLeague(y);
      setLeagueInfo(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "League error");
      setLeagueInfo(null);
    } finally {
      setLoadingLeague(false);
    }
  };

  const fetchTeamHistory = async (y, teamId) => {
    if (!y || !teamId) return;
    setLoadingHistory(true);
    setError(null);
    try {
      const data = await api.getTeamHistory(y, teamId);
      setTeamHistory(data);
    } catch (e) {
      console.error(e);
      setError(e.message || "Team history error");
      setTeamHistory(null);
    } finally {
      setLoadingHistory(false);
    }
  };

  const handleRefresh = () => {
    if (year && week) fetchWeekPower(year, week);
    if (year) fetchSeasonPower(year);
    if (standingsYear) fetchLeague(standingsYear);
    if (tab === "history" && year && selectedTeamId) {
      fetchTeamHistory(year, selectedTeamId);
    }
  };

  // ---- effects ----

  // First load: meta for default season, then week + season power
  useEffect(() => {
    const bootstrap = async () => {
      const data = await fetchMeta();
      if (!data) return;

      const y = data.year;
      if (y) setYear(y);

      const weeks = data.weeks || [];
      if (!weeks.length) return;

      let defaultWeek =
        data.currentWeek && weeks.includes(data.currentWeek)
          ? data.currentWeek
          : weeks[weeks.length - 1];

      setWeek(defaultWeek);

      fetchWeekPower(y, defaultWeek);
      fetchSeasonPower(y);
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

      fetchWeekPower(year, w);
      fetchSeasonPower(year);

      // if selected team doesn’t exist this year, clear history selection
      if (
        selectedTeamId &&
        !teamsForYear.some((t) => t.teamId === selectedTeamId)
      ) {
        setSelectedTeamId(null);
        setTeamHistory(null);
      }
    };
    loadYear();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year]);

  // ESPN standings: always latest season (standingsYear)
  useEffect(() => {
    if (!standingsYear) return;
    fetchLeague(standingsYear);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standingsYear]);

  // If we are on history tab and selection changes, fetch history
  useEffect(() => {
    if (tab !== "history") return;
    if (!year || !selectedTeamId) return;
    fetchTeamHistory(year, selectedTeamId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, year, selectedTeamId]);

  // ---- UI helpers ----

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
        { id: "history", label: "History" },
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
          leagueInfo={leagueInfo}
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
          meta={meta}
          teams={teamsForYear}
          selectedTeamId={selectedTeamId}
          setSelectedTeamId={setSelectedTeamId}
          teamHistory={teamHistory}
          loadingHistory={loadingHistory}
          categories={CATEGORIES}
        />
      )}
    </div>
  );
}

export default App;