import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:5001";

const thStyle = {
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "1px solid #1e293b",
  position: "sticky",
  top: 0,
  background: "#020617",
};

const tdStyle = {
  padding: "6px 8px",
  borderBottom: "1px solid #1e293b",
};

const CATEGORIES = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"];

function renderZCell(z) {
  const value = Number.isFinite(z) ? z : 0;
  let bg = "transparent";
  let color = "#e5e7eb";

  if (value >= 1.0) {
    bg = "rgba(34,197,94,0.25)";
    color = "#bbf7d0";
  } else if (value >= 0.3) {
    bg = "rgba(34,197,94,0.15)";
  } else if (value <= -1.0) {
    bg = "rgba(248,113,113,0.25)";
    color = "#fecaca";
  } else if (value <= -0.3) {
    bg = "rgba(248,113,113,0.15)";
  }

  return (
    <td style={{ ...tdStyle, background: bg, color }}>
      {value.toFixed(2)}
    </td>
  );
}

function TeamHistoryChart({ history, selectedCategory }) {
  if (!history || history.length === 0) return null;

  const points = [];
  let label = "";

  if (selectedCategory === "RANK") {
    label = "Weekly Rank (lower is better)";
    history.forEach((h) => {
      if (h.rank != null) {
        points.push({ x: h.week, y: h.rank });
      }
    });
    if (points.length === 0) return null;
  } else if (selectedCategory === "TOTAL") {
    label = "Total Z-score per week";
    history.forEach((h) => {
      const y = typeof h.totalZ === "number" ? h.totalZ : 0;
      points.push({ x: h.week, y });
    });
  } else {
    const key = `${selectedCategory}_z`;
    label = `${selectedCategory} Z-score per week`;
    history.forEach((h) => {
      const zs = h.zscores || {};
      const v = zs[key];
      if (typeof v === "number") {
        points.push({ x: h.week, y: v });
      }
    });
    if (points.length === 0) return null;
  }

  if (points.length === 0) return null;

  const minX = Math.min(...points.map((p) => p.x));
  const maxX = Math.max(...points.map((p) => p.x));
  let minY = Math.min(...points.map((p) => p.y));
  let maxY = Math.max(...points.map((p) => p.y));

  if (selectedCategory === "RANK") {
    minY = 1;
    maxY = Math.max(...points.map((p) => p.y));
  } else if (minY === maxY) {
    minY -= 1;
    maxY += 1;
  }

  const width = 640;
  const height = 220;
  const padding = 32;

  const xScale = (x) => {
    if (maxX === minX) return width / 2;
    return (
      padding +
      ((x - minX) / (maxX - minX)) * (width - 2 * padding)
    );
  };

  const yScale = (y) => {
    if (maxY === minY) return height / 2;
    const t = (y - minY) / (maxY - minY);
    return padding + (1 - t) * (height - 2 * padding);
  };

  const linePath = points
    .map((p, idx) => {
      const x = xScale(p.x);
      const y = yScale(p.y);
      return `${idx === 0 ? "M" : "L"} ${x} ${y}`;
    })
    .join(" ");

  return (
    <div style={{ marginBottom: "16px" }}>
      <div style={{ fontSize: "0.9rem", marginBottom: 4 }}>{label}</div>
      <svg
        width={width}
        height={height}
        style={{
          maxWidth: "100%",
          background: "#020617",
          borderRadius: 8,
        }}
      >
        <line
          x1={padding}
          y1={height - padding}
          x2={width - padding}
          y2={height - padding}
          stroke="#334155"
          strokeWidth="1"
        />
        <line
          x1={padding}
          y1={padding}
          x2={padding}
          y2={height - padding}
          stroke="#334155"
          strokeWidth="1"
        />

        <path
          d={linePath}
          fill="none"
          stroke="#38bdf8"
          strokeWidth="2"
        />

        {points.map((p, idx) => {
          const x = xScale(p.x);
          const y = yScale(p.y);
          return <circle key={idx} cx={x} cy={y} r={3} fill="#38bdf8" />;
        })}
      </svg>
    </div>
  );
}

function App() {
  const [tab, setTab] = useState("overview"); // 'overview' | 'dashboard'

  const [year, setYear] = useState(2025);
  const [week, setWeek] = useState(1);

  const [meta, setMeta] = useState({ years: [], weeks: [], year: 2025 });

  const [weekPower, setWeekPower] = useState(null);
  const [seasonPower, setSeasonPower] = useState(null);

  const [loadingWeek, setLoadingWeek] = useState(false);
  const [loadingSeason, setLoadingSeason] = useState(false);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [error, setError] = useState(null);

  // Dashboard-specific state
  const [metricMode, setMetricMode] = useState("weekly_power"); // 'weekly_power' | 'season_power' | 'team_history'
  const [selectedTeamId, setSelectedTeamId] = useState("ALL");
  const [selectedCategory, setSelectedCategory] = useState("TOTAL");

  const [teamHistory, setTeamHistory] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Sorting
  const [sortField, setSortField] = useState("RANK"); // depends on metric
  const [sortDirection, setSortDirection] = useState("ASC"); // 'ASC' | 'DESC'

  // ---- API helpers ----

  const fetchMeta = async (y) => {
    setLoadingMeta(true);
    setError(null);
    try {
      const url =
        y != null ? `${API_BASE}/api/meta?year=${y}` : `${API_BASE}/api/meta`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Meta error: ${res.status}`);
      const data = await res.json();
      setMeta(data);

      if (!year) setYear(data.year);
      if (!week && data.weeks && data.weeks.length > 0) {
        const lastWeek = data.weeks[data.weeks.length - 1];
        setWeek(lastWeek);
      }
    } catch (e) {
      console.error(e);
      setError(e.message);
    } finally {
      setLoadingMeta(false);
    }
  };

  const fetchWeekPower = async (y, w) => {
    if (!y || !w) return;
    setLoadingWeek(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/api/analysis/week-power?year=${y}&week=${w}`
      );
      if (!res.ok) throw new Error(`Week power error: ${res.status}`);
      const data = await res.json();
      setWeekPower(data);
    } catch (e) {
      console.error(e);
      setError(e.message);
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
      const res = await fetch(
        `${API_BASE}/api/analysis/season-power?year=${y}`
      );
      if (!res.ok) throw new Error(`Season power error: ${res.status}`);
      const data = await res.json();
      setSeasonPower(data);
    } catch (e) {
      console.error(e);
      setError(e.message);
      setSeasonPower(null);
    } finally {
      setLoadingSeason(false);
    }
  };

  const fetchTeamHistory = async (y, teamId) => {
    if (!y || !teamId || teamId === "ALL") {
      setTeamHistory(null);
      return;
    }
    setLoadingHistory(true);
    setError(null);
    try {
      const res = await fetch(
        `${API_BASE}/api/analysis/team-history?year=${y}&teamId=${teamId}`
      );
      if (!res.ok) throw new Error(`Team history error: ${res.status}`);
      const data = await res.json();
      setTeamHistory(data);
    } catch (e) {
      console.error(e);
      setError(e.message);
      setTeamHistory(null);
    } finally {
      setLoadingHistory(false);
    }
  };

  // ---- Initial load ----
  useEffect(() => {
    const bootstrap = async () => {
      await fetchMeta();
    };
    bootstrap();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When meta changes and year/week are known, load power data
  useEffect(() => {
    if (!year) return;

    if (meta.weeks && meta.weeks.length > 0) {
      const lastWeek = meta.weeks[meta.weeks.length - 1];
      if (!week || !meta.weeks.includes(week)) {
        setWeek(lastWeek);
        fetchWeekPower(year, lastWeek);
      } else {
        fetchWeekPower(year, week);
      }
    }

    fetchSeasonPower(year);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [meta.year]);

  // When year changes via UI, refresh meta (weeks) + power
  useEffect(() => {
    if (!year) return;
    fetchMeta(year);
    fetchSeasonPower(year);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year]);

  // When week changes, refresh weekly power
  useEffect(() => {
    if (!year || !week) return;
    fetchWeekPower(year, week);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [week]);

  // When metric mode or selected team changes, refresh team history if needed
  useEffect(() => {
    if (metricMode === "team_history" && selectedTeamId !== "ALL") {
      fetchTeamHistory(year, selectedTeamId);
    } else {
      setTeamHistory(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [metricMode, selectedTeamId, year]);

  const handleRefresh = () => {
    if (year && week) {
      fetchWeekPower(year, week);
    }
    if (year) {
      fetchSeasonPower(year);
    }
    if (metricMode === "team_history" && selectedTeamId !== "ALL") {
      fetchTeamHistory(year, selectedTeamId);
    }
  };

  const weekTeams = weekPower?.teams || [];
  const seasonTeams = seasonPower?.teams || [];

  // Build team options from whichever data is available
  const teamOptions = useMemo(() => {
    const map = new Map();
    weekTeams.forEach((t) => map.set(t.teamId, t.teamName));
    seasonTeams.forEach((t) => map.set(t.teamId, t.teamName));

    const options = Array.from(map.entries())
      .filter(([id]) => id !== 0)
      .map(([id, name]) => ({ id, name }));

    options.sort((a, b) => a.name.localeCompare(b.name));
    return options;
  }, [weekTeams, seasonTeams]);

  // ---------- sorting helpers ----------

  const compareStrings = (a, b) => {
    const sa = (a ?? "").toString();
    const sb = (b ?? "").toString();
    const cmp = sa.localeCompare(sb);
    return sortDirection === "ASC" ? cmp : -cmp;
  };

  const compareNumbers = (a, b) => {
    const na = typeof a === "number" ? a : Number.NEGATIVE_INFINITY;
    const nb = typeof b === "number" ? b : Number.NEGATIVE_INFINITY;
    if (na === nb) return 0;
    if (sortDirection === "ASC") return na - nb;
    return nb - na;
  };

  const sortedWeekTeams = useMemo(() => {
    let teams = weekTeams;
    if (selectedTeamId !== "ALL") {
      teams = teams.filter((t) => t.teamId === Number(selectedTeamId));
    }
    if (!teams || teams.length === 0) return [];

    const copy = [...teams];

    if (metricMode !== "weekly_power") {
      return copy;
    }

    return copy.sort((a, b) => {
      if (sortField === "TEAM_NAME") {
        return compareStrings(a.teamName, b.teamName);
      }

      if (sortField === "RANK") {
        const av = a.rank ?? 999;
        const bv = b.rank ?? 999;
        return sortDirection === "ASC" ? av - bv : bv - av;
      }

      if (sortField === "TOTAL_Z") {
        return compareNumbers(a.totalZ, b.totalZ);
      }

      // assume category label, e.g. "FG%"
      const key = `${sortField}_z`;
      const av = a.perCategoryZ?.[key];
      const bv = b.perCategoryZ?.[key];
      return compareNumbers(av, bv);
    });
  }, [weekTeams, selectedTeamId, metricMode, sortField, sortDirection]);

  const sortedSeasonTeams = useMemo(() => {
    let teams = seasonTeams;
    if (selectedTeamId !== "ALL") {
      teams = teams.filter((t) => t.teamId === Number(selectedTeamId));
    }
    if (!teams || teams.length === 0) return [];

    const copy = [...teams];

    if (metricMode !== "season_power") {
      return copy;
    }

    return copy.sort((a, b) => {
      if (sortField === "TEAM_NAME") {
        return compareStrings(a.teamName, b.teamName);
      }

      if (sortField === "RANK") {
        const av = a.rank ?? 999;
        const bv = b.rank ?? 999;
        return sortDirection === "ASC" ? av - bv : bv - av;
      }

      if (sortField === "AVG_TOTAL_Z") {
        return compareNumbers(a.avgTotalZ, b.avgTotalZ);
      }

      if (sortField === "SUM_TOTAL_Z") {
        return compareNumbers(a.sumTotalZ, b.sumTotalZ);
      }

      // default: keep original if unknown
      return 0;
    });
  }, [seasonTeams, selectedTeamId, metricMode, sortField, sortDirection]);

  // ---------- RENDER ----------

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
      ].map((t) => {
        const active = tab === t.id;
        return (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              border: "none",
              borderBottom: active ? "2px solid #38bdf8" : "2px solid transparent",
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

  const renderFiltersRow = () => {
    const sortOptionsWeekly = [
      { value: "RANK", label: "Rank" },
      { value: "TOTAL_Z", label: "Total Z" },
      ...CATEGORIES.map((c) => ({ value: c, label: `${c} Z` })),
      { value: "TEAM_NAME", label: "Team Name" },
    ];

    const sortOptionsSeason = [
      { value: "RANK", label: "Rank" },
      { value: "AVG_TOTAL_Z", label: "Avg Total Z" },
      { value: "SUM_TOTAL_Z", label: "Sum Total Z" },
      { value: "TEAM_NAME", label: "Team Name" },
    ];

    const sortOptions =
      metricMode === "season_power" ? sortOptionsSeason : sortOptionsWeekly;

    return (
      <section
        style={{
          marginBottom: "16px",
          display: "flex",
          flexWrap: "wrap",
          gap: "12px",
          alignItems: "center",
        }}
      >
        {/* Year */}
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

        {/* Week */}
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

        {/* Metric Mode */}
        <div>
          <label style={{ fontSize: "0.9rem" }}>Metric</label>
          <select
            value={metricMode}
            onChange={(e) => setMetricMode(e.target.value)}
            style={{
              display: "block",
              marginTop: "4px",
              padding: "4px 8px",
              borderRadius: "6px",
              border: "1px solid #334155",
              background: "#020617",
              color: "#e5e7eb",
              minWidth: "180px",
            }}
          >
            <option value="weekly_power">Weekly Power (this week)</option>
            <option value="season_power">Season Power (avg)</option>
            <option value="team_history">Team History (week over week)</option>
          </select>
        </div>

        {/* Team */}
        <div>
          <label style={{ fontSize: "0.9rem" }}>Team</label>
          <select
            value={selectedTeamId}
            onChange={(e) => setSelectedTeamId(e.target.value)}
            style={{
              display: "block",
              marginTop: "4px",
              padding: "4px 8px",
              borderRadius: "6px",
              border: "1px solid #334155",
              background: "#020617",
              color: "#e5e7eb",
              minWidth: "180px",
            }}
          >
            <option value="ALL">All teams</option>
            {teamOptions.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>

        {/* Category (for charts / summaries) */}
        <div>
          <label style={{ fontSize: "0.9rem" }}>Category</label>
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            style={{
              display: "block",
              marginTop: "4px",
              padding: "4px 8px",
              borderRadius: "6px",
              border: "1px solid #334155",
              background: "#020617",
              color: "#e5e7eb",
              minWidth: "140px",
            }}
          >
            <option value="TOTAL">Total Z (all cats)</option>
            <option value="RANK">Rank (weekly)</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>

        {/* Sort By */}
        {metricMode !== "team_history" && (
          <>
            <div>
              <label style={{ fontSize: "0.9rem" }}>Sort by</label>
              <select
                value={sortField}
                onChange={(e) => setSortField(e.target.value)}
                style={{
                  display: "block",
                  marginTop: "4px",
                  padding: "4px 8px",
                  borderRadius: "6px",
                  border: "1px solid #334155",
                  background: "#020617",
                  color: "#e5e7eb",
                  minWidth: "150px",
                }}
              >
                {sortOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Sort Direction */}
            <div>
              <label style={{ fontSize: "0.9rem" }}>Direction</label>
              <select
                value={sortDirection}
                onChange={(e) => setSortDirection(e.target.value)}
                style={{
                  display: "block",
                  marginTop: "4px",
                  padding: "4px 8px",
                  borderRadius: "6px",
                  border: "1px solid #334155",
                  background: "#020617",
                  color: "#e5e7eb",
                  minWidth: "130px",
                }}
              >
                <option value="DESC">Best → Worst</option>
                <option value="ASC">Worst → Best</option>
              </select>
            </div>
          </>
        )}

        {/* Refresh */}
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
          <span style={{ color: "#fca5a5", fontSize: "0.85rem" }}>{error}</span>
        )}
      </section>
    );
  };

  const renderOverviewTab = () => (
    <>
      {/* Weekly Power Table */}
      <section
        style={{
          marginBottom: "24px",
          padding: "16px",
          borderRadius: "12px",
          background: "rgba(15,23,42,0.9)",
          boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
        }}
      >
        <h2 style={{ marginTop: 0, fontSize: "1.2rem" }}>
          Weekly Power Rankings
        </h2>
        <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
          Total Z-score across FG%, FT%, 3PM, REB, AST, STL, BLK, DD, PTS.
        </p>

        {loadingWeek && <div>Loading week data...</div>}

        {!loadingWeek && weekPower && weekPower.teams?.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
            No data for this week/year.
          </div>
        )}

        {!loadingWeek && weekPower && weekPower.teams?.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "0.9rem",
              }}
            >
              <thead>
                <tr>
                  <th style={thStyle}>Rank</th>
                  <th style={thStyle}>Team</th>
                  <th style={thStyle}>Total Z</th>
                  <th style={thStyle}>FG%</th>
                  <th style={thStyle}>FT%</th>
                  <th style={thStyle}>3PM</th>
                  <th style={thStyle}>REB</th>
                  <th style={thStyle}>AST</th>
                  <th style={thStyle}>STL</th>
                  <th style={thStyle}>BLK</th>
                  <th style={thStyle}>DD</th>
                  <th style={thStyle}>PTS</th>
                </tr>
              </thead>
              <tbody>
                {weekPower.teams.map((t) => {
                  const perCat = t.perCategoryZ || {};
                  const totalZ =
                    typeof t.totalZ === "number" ? t.totalZ : 0;

                  return (
                    <tr key={t.teamId}>
                      <td style={tdStyle}>{t.rank ?? "-"}</td>
                      <td style={{ ...tdStyle, fontWeight: 600 }}>
                        {t.teamName}
                        {t.isLeagueAverage && (
                          <span style={{ color: "#38bdf8", marginLeft: 4 }}>
                            (League Avg)
                          </span>
                        )}
                      </td>
                      <td style={{ ...tdStyle, fontWeight: 600 }}>
                        {totalZ.toFixed(2)}
                      </td>
                      {renderZCell(perCat["FG%_z"] ?? 0)}
                      {renderZCell(perCat["FT%_z"] ?? 0)}
                      {renderZCell(perCat["3PM_z"] ?? 0)}
                      {renderZCell(perCat["REB_z"] ?? 0)}
                      {renderZCell(perCat["AST_z"] ?? 0)}
                      {renderZCell(perCat["STL_z"] ?? 0)}
                      {renderZCell(perCat["BLK_z"] ?? 0)}
                      {renderZCell(perCat["DD_z"] ?? 0)}
                      {renderZCell(perCat["PTS_z"] ?? 0)}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Season Power Table */}
      <section
        style={{
          marginBottom: "24px",
          padding: "16px",
          borderRadius: "12px",
          background: "rgba(15,23,42,0.9)",
          boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
        }}
      >
        <h2 style={{ marginTop: 0, fontSize: "1.2rem" }}>
          Season Power Rankings
        </h2>
        <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
          Averaged total Z-score across all weeks played.
        </p>

        {loadingSeason && <div>Loading season data...</div>}

        {!loadingSeason &&
          seasonPower &&
          seasonPower.teams?.length === 0 && (
            <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
              No season data for this year.
            </div>
          )}

        {!loadingSeason &&
          seasonPower &&
          seasonPower.teams?.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: "0.9rem",
                }}
              >
                <thead>
                  <tr>
                    <th style={thStyle}>Rank</th>
                    <th style={thStyle}>Team</th>
                    <th style={thStyle}>Weeks</th>
                    <th style={thStyle}>Avg Total Z</th>
                    <th style={thStyle}>Sum Total Z</th>
                  </tr>
                </thead>
                <tbody>
                  {seasonPower.teams.map((t) => {
                    const avgZ =
                      typeof t.avgTotalZ === "number" ? t.avgTotalZ : 0;
                    const sumZ =
                      typeof t.sumTotalZ === "number" ? t.sumTotalZ : 0;

                    return (
                      <tr key={t.teamId}>
                        <td style={tdStyle}>{t.rank ?? "-"}</td>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>
                          {t.teamName}
                        </td>
                        <td style={tdStyle}>{t.weeks ?? "-"}</td>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>
                          {avgZ.toFixed(2)}
                        </td>
                        <td style={tdStyle}>{sumZ.toFixed(2)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
      </section>
    </>
  );

  const renderDashboardTab = () => {
    return (
      <>
        {renderFiltersRow()}

        {/* Summary chips */}
        <section
          style={{
            marginBottom: "16px",
            display: "flex",
            flexWrap: "wrap",
            gap: "12px",
          }}
        >
          {metricMode === "weekly_power" && sortedWeekTeams.length > 0 && (
            <>
              {(() => {
                const sorted = [...sortedWeekTeams].sort(
                  (a, b) => (b.totalZ || 0) - (a.totalZ || 0)
                );
                const best = sorted[0];
                const worst = sorted[sorted.length - 1];
                const catKey =
                  selectedCategory === "TOTAL" || selectedCategory === "RANK"
                    ? null
                    : `${selectedCategory}_z`;
                return (
                  <>
                    <div
                      style={{
                        padding: "10px 14px",
                        borderRadius: "10px",
                        background: "rgba(22,163,74,0.1)",
                        border: "1px solid rgba(34,197,94,0.4)",
                        minWidth: "220px",
                      }}
                    >
                      <div
                        style={{
                          fontSize: "0.8rem",
                          color: "#bbf7d0",
                          marginBottom: 4,
                        }}
                      >
                        Weekly MVP (Total Z)
                      </div>
                      <div style={{ fontWeight: 600 }}>{best.teamName}</div>
                      <div style={{ fontSize: "0.9rem", color: "#a7f3d0" }}>
                        {best.totalZ.toFixed(2)} Z
                      </div>
                    </div>

                    <div
                      style={{
                        padding: "10px 14px",
                        borderRadius: "10px",
                        background: "rgba(239,68,68,0.1)",
                        border: "1px solid rgba(248,113,113,0.4)",
                        minWidth: "220px",
                      }}
                    >
                      <div
                        style={{
                          fontSize: "0.8rem",
                          color: "#fecaca",
                          marginBottom: 4,
                        }}
                      >
                        Weekly LVP (Total Z)
                      </div>
                      <div style={{ fontWeight: 600 }}>{worst.teamName}</div>
                      <div style={{ fontSize: "0.9rem", color: "#fecaca" }}>
                        {worst.totalZ.toFixed(2)} Z
                      </div>
                    </div>

                    {catKey && (
                      <div
                        style={{
                          padding: "10px 14px",
                          borderRadius: "10px",
                          background: "rgba(37,99,235,0.1)",
                          border: "1px solid rgba(59,130,246,0.4)",
                          minWidth: "220px",
                        }}
                      >
                        <div
                          style={{
                            fontSize: "0.8rem",
                            color: "#bfdbfe",
                            marginBottom: 4,
                          }}
                        >
                          Category Leader ({selectedCategory})
                        </div>
                        {(() => {
                          const ranked = [...sortedWeekTeams].sort((a, b) => {
                            const az =
                              a.perCategoryZ?.[catKey] ??
                              Number.NEGATIVE_INFINITY;
                            const bz =
                              b.perCategoryZ?.[catKey] ??
                              Number.NEGATIVE_INFINITY;
                            return bz - az;
                          });
                          const leader = ranked[0];
                          const z =
                            leader?.perCategoryZ?.[catKey] ?? 0;
                          return (
                            <>
                              <div style={{ fontWeight: 600 }}>
                                {leader?.teamName}
                              </div>
                              <div
                                style={{
                                  fontSize: "0.9rem",
                                  color: "#bfdbfe",
                                }}
                              >
                                {z.toFixed(2)} Z in {selectedCategory}
                              </div>
                            </>
                          );
                        })()}
                      </div>
                    )}
                  </>
                );
              })()}
            </>
          )}

          {metricMode === "season_power" && sortedSeasonTeams.length > 0 && (
            <>
              {(() => {
                const sorted = [...sortedSeasonTeams].sort(
                  (a, b) => (b.avgTotalZ || 0) - (a.avgTotalZ || 0)
                );
                const best = sorted[0];
                const worst = sorted[sorted.length - 1];
                return (
                  <>
                    <div
                      style={{
                        padding: "10px 14px",
                        borderRadius: "10px",
                        background: "rgba(56,189,248,0.1)",
                        border: "1px solid rgba(56,189,248,0.4)",
                        minWidth: "220px",
                      }}
                    >
                      <div
                        style={{
                          fontSize: "0.8rem",
                          color: "#bae6fd",
                          marginBottom: 4,
                        }}
                      >
                        Season Juggernaut
                      </div>
                      <div style={{ fontWeight: 600 }}>{best.teamName}</div>
                      <div style={{ fontSize: "0.9rem", color: "#7dd3fc" }}>
                        {best.avgTotalZ.toFixed(2)} avg Z
                      </div>
                    </div>

                    <div
                      style={{
                        padding: "10px 14px",
                        borderRadius: "10px",
                        background: "rgba(148,163,184,0.1)",
                        border: "1px solid rgba(148,163,184,0.4)",
                        minWidth: "220px",
                      }}
                    >
                      <div
                        style={{
                          fontSize: "0.8rem",
                          color: "#e5e7eb",
                          marginBottom: 4,
                        }}
                      >
                        Season Doormat
                      </div>
                      <div style={{ fontWeight: 600 }}>{worst.teamName}</div>
                      <div style={{ fontSize: "0.9rem", color: "#e5e7eb" }}>
                        {worst.avgTotalZ.toFixed(2)} avg Z
                      </div>
                    </div>
                  </>
                );
              })()}
            </>
          )}

          {metricMode === "team_history" &&
            selectedTeamId !== "ALL" &&
            teamHistory && (
              <div
                style={{
                  padding: "10px 14px",
                  borderRadius: "10px",
                  background: "rgba(251,191,36,0.1)",
                  border: "1px solid rgba(251,191,36,0.4)",
                  minWidth: "260px",
                }}
              >
                <div
                  style={{
                    fontSize: "0.8rem",
                    color: "#facc15",
                    marginBottom: 4,
                  }}
                >
                  Team Trend ·{" "}
                  {selectedCategory === "TOTAL"
                    ? "Total Z"
                    : selectedCategory === "RANK"
                    ? "Rank"
                    : selectedCategory}
                </div>
                <div style={{ fontWeight: 600 }}>{teamHistory.teamName}</div>
                <div style={{ fontSize: "0.9rem", color: "#fef3c7" }}>
                  Weeks: {teamHistory.history?.length ?? 0}
                </div>
              </div>
            )}
        </section>

        {/* Main table area based on metricMode */}
        <section
          style={{
            marginBottom: "24px",
            padding: "16px",
            borderRadius: "12px",
            background: "rgba(15,23,42,0.9)",
            boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
          }}
        >
          {metricMode === "weekly_power" && (
            <>
              <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>
                Weekly Power · Filtered View
              </h2>
              {loadingWeek && <div>Loading week data...</div>}
              {!loadingWeek && sortedWeekTeams.length === 0 && (
                <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
                  No data for this week / filters.
                </div>
              )}
              {!loadingWeek && sortedWeekTeams.length > 0 && (
                <div style={{ overflowX: "auto" }}>
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      fontSize: "0.9rem",
                    }}
                  >
                    <thead>
                      <tr>
                        <th style={thStyle}>Rank</th>
                        <th style={thStyle}>Team</th>
                        <th style={thStyle}>Total Z</th>
                        {CATEGORIES.map((cat) => (
                          <th key={cat} style={thStyle}>
                            {cat}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sortedWeekTeams.map((t) => {
                        const perCat = t.perCategoryZ || {};
                        const totalZ =
                          typeof t.totalZ === "number" ? t.totalZ : 0;

                        return (
                          <tr key={t.teamId}>
                            <td style={tdStyle}>{t.rank ?? "-"}</td>
                            <td style={{ ...tdStyle, fontWeight: 600 }}>
                              {t.teamName}
                              {t.isLeagueAverage && (
                                <span
                                  style={{ color: "#38bdf8", marginLeft: 4 }}
                                >
                                  (League Avg)
                                </span>
                              )}
                            </td>
                            <td style={{ ...tdStyle, fontWeight: 600 }}>
                              {totalZ.toFixed(2)}
                            </td>
                            {CATEGORIES.map((cat) => {
                              const key = `${cat}_z`;
                              return renderZCell(perCat[key] ?? 0);
                            })}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {metricMode === "season_power" && (
            <>
              <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>
                Season Power · Filtered View
              </h2>
              {loadingSeason && <div>Loading season data...</div>}
              {!loadingSeason && sortedSeasonTeams.length === 0 && (
                <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
                  No data for this year / filters.
                </div>
              )}
              {!loadingSeason && sortedSeasonTeams.length > 0 && (
                <div style={{ overflowX: "auto" }}>
                  <table
                    style={{
                      width: "100%",
                      borderCollapse: "collapse",
                      fontSize: "0.9rem",
                    }}
                  >
                    <thead>
                      <tr>
                        <th style={thStyle}>Rank</th>
                        <th style={thStyle}>Team</th>
                        <th style={thStyle}>Weeks</th>
                        <th style={thStyle}>Avg Total Z</th>
                        <th style={thStyle}>Sum Total Z</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedSeasonTeams.map((t) => {
                        const avgZ =
                          typeof t.avgTotalZ === "number" ? t.avgTotalZ : 0;
                        const sumZ =
                          typeof t.sumTotalZ === "number" ? t.sumTotalZ : 0;

                        return (
                          <tr key={t.teamId}>
                            <td style={tdStyle}>{t.rank ?? "-"}</td>
                            <td style={{ ...tdStyle, fontWeight: 600 }}>
                              {t.teamName}
                            </td>
                            <td style={tdStyle}>{t.weeks ?? "-"}</td>
                            <td style={{ ...tdStyle, fontWeight: 600 }}>
                              {avgZ.toFixed(2)}
                            </td>
                            <td style={tdStyle}>{sumZ.toFixed(2)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          {metricMode === "team_history" && (
            <>
              <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>
                Team History · Week over Week
              </h2>
              {selectedTeamId === "ALL" && (
                <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
                  Select a specific team to see its history.
                </div>
              )}
              {selectedTeamId !== "ALL" && loadingHistory && (
                <div>Loading team history...</div>
              )}
              {selectedTeamId !== "ALL" &&
                !loadingHistory &&
                teamHistory &&
                teamHistory.history?.length === 0 && (
                  <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
                    No history for this team / year.
                  </div>
                )}

              {selectedTeamId !== "ALL" &&
                !loadingHistory &&
                teamHistory &&
                teamHistory.history?.length > 0 && (
                  <>
                    <TeamHistoryChart
                      history={teamHistory.history}
                      selectedCategory={selectedCategory}
                    />

                    <div style={{ overflowX: "auto" }}>
                      <table
                        style={{
                          width: "100%",
                          borderCollapse: "collapse",
                          fontSize: "0.9rem",
                        }}
                      >
                        <thead>
                          <tr>
                            <th style={thStyle}>Week</th>
                            <th style={thStyle}>Total Z</th>
                            {selectedCategory === "TOTAL" ||
                            selectedCategory === "RANK" ? (
                              <>
                                <th style={thStyle}>FG% Z</th>
                                <th style={thStyle}>FT% Z</th>
                                <th style={thStyle}>3PM Z</th>
                                <th style={thStyle}>REB Z</th>
                                <th style={thStyle}>AST Z</th>
                                <th style={thStyle}>STL Z</th>
                                <th style={thStyle}>BLK Z</th>
                                <th style={thStyle}>DD Z</th>
                                <th style={thStyle}>PTS Z</th>
                              </>
                            ) : (
                              <th style={thStyle}>{selectedCategory} Z</th>
                            )}
                          </tr>
                        </thead>
                        <tbody>
                          {teamHistory.history.map((entry) => {
                            const week = entry.week;
                            const zs = entry.zscores || {};
                            const totalZ = Object.values(zs).reduce(
                              (sum, v) => sum + (Number(v) || 0),
                              0
                            );

                            if (
                              selectedCategory === "TOTAL" ||
                              selectedCategory === "RANK"
                            ) {
                              return (
                                <tr key={week}>
                                  <td style={tdStyle}>{week}</td>
                                  <td style={{ ...tdStyle, fontWeight: 600 }}>
                                    {totalZ.toFixed(2)}
                                  </td>
                                  {CATEGORIES.map((cat) => {
                                    const key = `${cat}_z`;
                                    return renderZCell(zs[key] ?? 0);
                                  })}
                                </tr>
                              );
                            } else {
                              const key = `${selectedCategory}_z`;
                              const val = zs[key] ?? 0;
                              return (
                                <tr key={week}>
                                  <td style={tdStyle}>{week}</td>
                                  <td style={{ ...tdStyle, fontWeight: 600 }}>
                                    {totalZ.toFixed(2)}
                                  </td>
                                  {renderZCell(val)}
                                </tr>
                              );
                            }
                          })}
                        </tbody>
                      </table>
                    </div>
                  </>
                )}
            </>
          )}
        </section>
      </>
    );
  };

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
          Fantasy Power Dashboard
        </h1>
        <p style={{ margin: "4px 0 0", color: "#94a3b8" }}>
          ESPN League {year} · Week {week}
        </p>
      </header>

      {renderTabs()}

      {loadingMeta && (
        <div style={{ marginBottom: "16px" }}>Loading league metadata…</div>
      )}

      {!loadingMeta && tab === "overview" && renderOverviewTab()}
      {!loadingMeta && tab === "dashboard" && renderDashboardTab()}
    </div>
  );
}

export default App;