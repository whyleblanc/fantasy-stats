import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_BASE = "http://127.0.0.1:5001";

const CATEGORIES = ["FG%", "FT%", "3PM", "REB", "AST", "STL", "BLK", "DD", "PTS"];

const thStyle = {
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "1px solid #1e293b",
  position: "sticky",
  top: 0,
  background: "#020617",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const tdStyle = {
  padding: "6px 8px",
  borderBottom: "1px solid #1e293b",
};

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

function SortHeader({ label, field, sortField, sortDirection, onSort }) {
  const isActive = sortField === field;
  const arrow = !isActive ? "" : sortDirection === "ASC" ? " ▲" : " ▼";

  return (
    <th
      style={thStyle}
      onClick={() => onSort(field)}
      title={isActive ? `Sorted by ${label} (${sortDirection})` : `Sort by ${label}`}
    >
      {label}
      {arrow}
    </th>
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
    return padding + ((x - minX) / (maxX - minX)) * (width - 2 * padding);
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
        {/* axes */}
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

        {/* line */}
        <path d={linePath} fill="none" stroke="#38bdf8" strokeWidth="2" />

        {/* points */}
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
  // ----- Top-level nav -----
  const [tab, setTab] = useState("overview"); // 'overview' | 'dashboard' | 'history'
  const [dashboardMode, setDashboardMode] = useState("weekly"); // 'weekly' | 'season' | 'team_history'
  const [historyMode, setHistoryMode] = useState("awards"); // 'awards' | 'team_history'

  // ----- Meta + filters -----
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

  const [selectedTeamId, setSelectedTeamId] = useState("ALL");
  const [selectedCategory, setSelectedCategory] = useState("TOTAL");

  // ----- Data -----
  const [weekPower, setWeekPower] = useState(null);
  const [seasonPower, setSeasonPower] = useState(null);
  const [leagueInfo, setLeagueInfo] = useState(null);
  const [teamHistory, setTeamHistory] = useState(null);

  // History / awards (multi-year)
  const [awardsByYear, setAwardsByYear] = useState([]); // [{year, champion,...}]
  const [multiSeasonTeams, setMultiSeasonTeams] = useState([]); // aggregated team history across seasons

  // ----- Loading / error -----
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [loadingWeek, setLoadingWeek] = useState(false);
  const [loadingSeason, setLoadingSeason] = useState(false);
  const [loadingLeague, setLoadingLeague] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [loadingAwards, setLoadingAwards] = useState(false);
  const [error, setError] = useState(null);

  // ----- Sorting -----
  const [sortField, setSortField] = useState("RANK");
  const [sortDirection, setSortDirection] = useState("ASC"); // 'ASC' | 'DESC'

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === "ASC" ? "DESC" : "ASC"));
    } else {
      setSortField(field);
      // default direction per field
      if (field === "RANK") {
        setSortDirection("ASC"); // 1 is best
      } else {
        setSortDirection("DESC"); // higher Z is better
      }
    }
  };

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

  // ----- API helpers -----
  const fetchMeta = async (y) => {
    setLoadingMeta(true);
    setError(null);
    try {
      const url =
        y != null ? `${API_BASE}/api/meta?year=${y}` : `${API_BASE}/api/meta`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Meta error: ${res.status}`);
      const data = await res.json();
      setMeta((prev) => ({ ...prev, ...data }));

      if (!year) setYear(data.year);
      if (data.currentWeek && (!week || !data.weeks?.includes(week))) {
        setWeek(data.currentWeek);
      }
    } catch (e) {
      console.error(e);
      setError(e.message);
    } finally {
      setLoadingMeta(false);
    }
  };

  const fetchLeague = async (y) => {
    if (!y) return;
    setLoadingLeague(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/league?year=${y}`);
      if (!res.ok) throw new Error(`League error: ${res.status}`);
      const data = await res.json();
      setLeagueInfo(data);
    } catch (e) {
      console.error(e);
      setError(e.message);
      setLeagueInfo(null);
    } finally {
      setLoadingLeague(false);
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

  const loadAwardsAcrossYears = async () => {
    if (!meta.years || meta.years.length === 0) return;
    setLoadingAwards(true);
    setError(null);

    const awards = [];
    const teamHistoryAgg = {}; // key: teamName

    for (const y of meta.years) {
      try {
        const res = await fetch(
          `${API_BASE}/api/analysis/season-power?year=${y}`
        );
        if (!res.ok) {
          // skip broken years
          continue;
        }
        const data = await res.json();
        const teams = data?.teams || [];
        if (!teams.length) continue;

        // sort by rank (if provided), then avgTotalZ
        const sortedByRank = [...teams].sort((a, b) => {
          const ra = a.rank ?? 999;
          const rb = b.rank ?? 999;
          if (ra !== rb) return ra - rb;
          const az = a.avgTotalZ ?? -999;
          const bz = b.avgTotalZ ?? -999;
          return bz - az;
        });

        const champion = sortedByRank[0];
        const second = sortedByRank[1];
        const third = sortedByRank[2];
        const last = sortedByRank[sortedByRank.length - 1];

        const bestAvg = [...teams].sort(
          (a, b) => (b.avgTotalZ ?? -999) - (a.avgTotalZ ?? -999)
        )[0];
        const worstAvg = [...teams].sort(
          (a, b) => (a.avgTotalZ ?? 999) - (b.avgTotalZ ?? 999)
        )[0];

        const bestSum = [...teams].sort(
          (a, b) => (b.sumTotalZ ?? -999) - (a.sumTotalZ ?? -999)
        )[0];
        const worstSum = [...teams].sort(
          (a, b) => (a.sumTotalZ ?? 999) - (b.sumTotalZ ?? 999)
        )[0];

        awards.push({
          year: y,
          champion: champion?.teamName ?? "-",
          second: second?.teamName ?? "-",
          third: third?.teamName ?? "-",
          last: last?.teamName ?? "-",
          bestAvgZ: bestAvg
            ? { team: bestAvg.teamName, value: bestAvg.avgTotalZ ?? 0 }
            : null,
          worstAvgZ: worstAvg
            ? { team: worstAvg.teamName, value: worstAvg.avgTotalZ ?? 0 }
            : null,
          bestTotalZ: bestSum
            ? { team: bestSum.teamName, value: bestSum.sumTotalZ ?? 0 }
            : null,
          worstTotalZ: worstSum
            ? { team: worstSum.teamName, value: worstSum.sumTotalZ ?? 0 }
            : null,
        });

        // accumulate multi-season stats by teamName
        for (const t of teams) {
          const key = t.teamName || `Team ${t.teamId}`;
          if (!teamHistoryAgg[key]) {
            teamHistoryAgg[key] = {
              teamName: key,
              seasons: 0,
              ranks: [],
              totalAvgZ: 0,
              totalSumZ: 0,
              bestAvgZ: null,
              worstAvgZ: null,
              bestTotalZ: null,
              worstTotalZ: null,
            };
          }
          const agg = teamHistoryAgg[key];
          agg.seasons += 1;

          const rank = t.rank ?? null;
          if (rank != null) {
            agg.ranks.push(rank);
          }

          const avgZ = t.avgTotalZ ?? 0;
          const sumZ = t.sumTotalZ ?? 0;

          agg.totalAvgZ += avgZ;
          agg.totalSumZ += sumZ;

          if (!agg.bestAvgZ || avgZ > agg.bestAvgZ.value) {
            agg.bestAvgZ = { year: y, value: avgZ };
          }
          if (!agg.worstAvgZ || avgZ < agg.worstAvgZ.value) {
            agg.worstAvgZ = { year: y, value: avgZ };
          }
          if (!agg.bestTotalZ || sumZ > agg.bestTotalZ.value) {
            agg.bestTotalZ = { year: y, value: sumZ };
          }
          if (!agg.worstTotalZ || sumZ < agg.worstTotalZ.value) {
            agg.worstTotalZ = { year: y, value: sumZ };
          }
        }
      } catch (e) {
        console.error(`Failed loading season-power for year ${y}`, e);
        // skip year
      }
    }

    // finalize multi-season teams
    const multiTeams = Object.values(teamHistoryAgg).map((agg) => {
      const avgRank =
        agg.ranks.length > 0
          ? agg.ranks.reduce((s, r) => s + r, 0) / agg.ranks.length
          : null;
      const bestFinish =
        agg.ranks.length > 0 ? Math.min(...agg.ranks) : null;
      const worstFinish =
        agg.ranks.length > 0 ? Math.max(...agg.ranks) : null;
      const avgZAcrossSeasons =
        agg.seasons > 0 ? agg.totalAvgZ / agg.seasons : 0;

      return {
        teamName: agg.teamName,
        seasons: agg.seasons,
        avgRank,
        bestFinish,
        worstFinish,
        avgZAcrossSeasons,
        bestAvgZ: agg.bestAvgZ,
        worstAvgZ: agg.worstAvgZ,
        bestTotalZ: agg.bestTotalZ,
        worstTotalZ: agg.worstTotalZ,
      };
    });

    multiTeams.sort((a, b) => {
      // best overall avgZ across seasons
      return (b.avgZAcrossSeasons ?? 0) - (a.avgZAcrossSeasons ?? 0);
    });

    setAwardsByYear(
      awards.sort((a, b) => (a.year ?? 0) - (b.year ?? 0))
    );
    setMultiSeasonTeams(multiTeams);
    setLoadingAwards(false);
  };

  // ----- Effects -----

  // Initial meta load
  useEffect(() => {
    fetchMeta();
  }, []);

  // When meta updated, align year/week + fetch data
  useEffect(() => {
    if (!meta.year) return;
    if (!meta.weeks || meta.weeks.length === 0) return;

    const effectiveYear = meta.year;
    setYear((prev) => prev || effectiveYear);

    const preferredWeek =
      meta.currentWeek && meta.weeks.includes(meta.currentWeek)
        ? meta.currentWeek
        : meta.weeks[meta.weeks.length - 1];

    setWeek((prev) =>
      prev && meta.weeks.includes(prev) ? prev : preferredWeek
    );

    fetchWeekPower(effectiveYear, preferredWeek);
    fetchSeasonPower(effectiveYear);
    fetchLeague(effectiveYear);
  }, [meta.year, meta.currentWeek, meta.weeks]);

  // When year changes via UI, refresh meta + season/league
  useEffect(() => {
    if (!year) return;
    fetchMeta(year);
    fetchSeasonPower(year);
    fetchLeague(year);
  }, [year]);

  // When week changes, refresh weekly power
  useEffect(() => {
    if (!year || !week) return;
    fetchWeekPower(year, week);
  }, [week, year]);

  // Dashboard: when in team_history mode and team selected, fetch team history
  useEffect(() => {
    if (dashboardMode === "team_history" && selectedTeamId !== "ALL") {
      fetchTeamHistory(year, selectedTeamId);
    } else {
      setTeamHistory(null);
    }
  }, [dashboardMode, selectedTeamId, year]);

  // History tab: load awards + multi-season stats once when needed
  useEffect(() => {
    if (tab === "history" && awardsByYear.length === 0 && !loadingAwards) {
      loadAwardsAcrossYears();
    }
  }, [tab, awardsByYear.length, loadingAwards, meta.years]);

  // ----- Derived data -----
  const weekTeams = weekPower?.teams || [];
  const seasonTeams = seasonPower?.teams || [];

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

  const filteredWeekTeams = useMemo(() => {
    let teams = weekTeams;
    if (selectedTeamId !== "ALL") {
      teams = teams.filter((t) => t.teamId === Number(selectedTeamId));
    }
    return teams;
  }, [weekTeams, selectedTeamId]);

  const filteredSeasonTeams = useMemo(() => {
    let teams = seasonTeams;
    if (selectedTeamId !== "ALL") {
      teams = teams.filter((t) => t.teamId === Number(selectedTeamId));
    }
    return teams;
  }, [seasonTeams, selectedTeamId]);

  const sortedWeekTeams = useMemo(() => {
    if (!filteredWeekTeams || filteredWeekTeams.length === 0) return [];
    if (dashboardMode !== "weekly" && tab !== "overview") {
      // default ranking when not in weekly dashboard or overview sorting
      return [...filteredWeekTeams].sort(
        (a, b) => (a.rank ?? 999) - (b.rank ?? 999)
      );
    }

    const copy = [...filteredWeekTeams];

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
  }, [filteredWeekTeams, sortField, sortDirection, compareNumbers, compareStrings, dashboardMode, tab]);

  const sortedSeasonTeams = useMemo(() => {
    if (!filteredSeasonTeams || filteredSeasonTeams.length === 0) return [];
    if (dashboardMode !== "season" && tab !== "history") {
      return [...filteredSeasonTeams].sort(
        (a, b) => (a.rank ?? 999) - (b.rank ?? 999)
      );
    }

    const copy = [...filteredSeasonTeams];

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

      return 0;
    });
  }, [filteredSeasonTeams, sortField, sortDirection, compareNumbers, compareStrings, dashboardMode, tab]);

  const handleRefresh = () => {
    if (year && week) {
      fetchWeekPower(year, week);
    }
    if (year) {
      fetchSeasonPower(year);
      fetchLeague(year);
    }
    if (dashboardMode === "team_history" && selectedTeamId !== "ALL") {
      fetchTeamHistory(year, selectedTeamId);
    }
  };

  // ----- Render helpers -----

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
      dashboardMode === "season" ? sortOptionsSeason : sortOptionsWeekly;

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
        {dashboardMode !== "season" && (
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
        )}

        {/* Dashboard metric mode (sub-tabs) */}
        {tab === "dashboard" && (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <label style={{ fontSize: "0.9rem" }}>View</label>
            <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
              {[
                { id: "weekly", label: "Weekly Power" },
                { id: "season", label: "Season Power" },
                { id: "team_history", label: "Team History" },
              ].map((mode) => {
                const active = dashboardMode === mode.id;
                return (
                  <button
                    key={mode.id}
                    onClick={() => setDashboardMode(mode.id)}
                    style={{
                      borderRadius: "999px",
                      border: "1px solid #334155",
                      padding: "4px 10px",
                      fontSize: "0.8rem",
                      cursor: "pointer",
                      background: active ? "#0f172a" : "transparent",
                      color: active ? "#e5e7eb" : "#9ca3af",
                    }}
                  >
                    {mode.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        {/* History sub-tabs */}
        {tab === "history" && (
          <div style={{ display: "flex", flexDirection: "column" }}>
            <label style={{ fontSize: "0.9rem" }}>History View</label>
            <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
              {[
                { id: "awards", label: "Awards (By Year)" },
                { id: "team_history", label: "Team History (All Seasons)" },
              ].map((mode) => {
                const active = historyMode === mode.id;
                return (
                  <button
                    key={mode.id}
                    onClick={() => setHistoryMode(mode.id)}
                    style={{
                      borderRadius: "999px",
                      border: "1px solid #334155",
                      padding: "4px 10px",
                      fontSize: "0.8rem",
                      cursor: "pointer",
                      background: active ? "#0f172a" : "transparent",
                      color: active ? "#e5e7eb" : "#9ca3af",
                    }}
                  >
                    {mode.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}

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
        {tab === "dashboard" && dashboardMode === "team_history" && (
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
        )}

        {/* Sort controls (only for dashboard weekly/season) */}
        {tab === "dashboard" && dashboardMode !== "team_history" && (
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
                {(dashboardMode === "season"
                  ? [
                      { value: "RANK", label: "Rank" },
                      { value: "AVG_TOTAL_Z", label: "Avg Total Z" },
                      { value: "SUM_TOTAL_Z", label: "Sum Total Z" },
                      { value: "TEAM_NAME", label: "Team Name" },
                    ]
                  : [
                      { value: "RANK", label: "Rank" },
                      { value: "TOTAL_Z", label: "Total Z" },
                      ...CATEGORIES.map((c) => ({
                        value: c,
                        label: `${c} Z`,
                      })),
                      { value: "TEAM_NAME", label: "Team Name" },
                    ]
                ).map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

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
          <span style={{ color: "#fca5a5", fontSize: "0.85rem" }}>
            {error}
          </span>
        )}
      </section>
    );
  };

  // ----- Overview Tab -----
  const renderOverviewTab = () => (
    <>
      {/* Weekly Power */}
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
          Weekly Power Rankings · Week {week}
        </h2>
        <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
          Total Z-score across FG%, FT%, 3PM, REB, AST, STL, BLK, DD, PTS.
        </p>

        {loadingWeek && <div>Loading week data...</div>}

        {!loadingWeek && (!weekPower || weekPower.teams?.length === 0) && (
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
                  <th style={{ ...thStyle, cursor: "default" }}>Rank</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Team</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Total Z</th>
                  {CATEGORIES.map((cat) => (
                    <th key={cat} style={{ ...thStyle, cursor: "default" }}>
                      {cat}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {weekPower.teams.map((t) => {
                  const perCat = t.perCategoryZ || {};
                  const totalZ = typeof t.totalZ === "number" ? t.totalZ : 0;

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
      </section>

      {/* Season Power */}
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
                    <th style={{ ...thStyle, cursor: "default" }}>Rank</th>
                    <th style={{ ...thStyle, cursor: "default" }}>Team</th>
                    <th style={{ ...thStyle, cursor: "default" }}>Weeks</th>
                    <th style={{ ...thStyle, cursor: "default" }}>
                      Avg Total Z
                    </th>
                    <th style={{ ...thStyle, cursor: "default" }}>
                      Sum Total Z
                    </th>
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

      {/* ESPN Standings */}
      <section
        style={{
          marginBottom: "24px",
          padding: "16px",
          borderRadius: "12px",
          background: "rgba(15,23,42,0.9)",
          boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
        }}
      >
        <h2 style={{ marginTop: 0, fontSize: "1.2rem" }}>ESPN Standings</h2>
        <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
          Raw standings from ESPN for season {year}. Sorted by final standing if
          available, otherwise by record and points for.
        </p>

        {loadingLeague && <div>Loading standings...</div>}

        {!loadingLeague && (!leagueInfo || !leagueInfo.teams?.length) && (
          <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
            No standings available for this year.
          </div>
        )}

        {!loadingLeague && leagueInfo && leagueInfo.teams?.length > 0 && (
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
                  <th style={{ ...thStyle, cursor: "default" }}>#</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Team</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Owner(s)</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Record</th>
                  <th style={{ ...thStyle, cursor: "default" }}>PF</th>
                  <th style={{ ...thStyle, cursor: "default" }}>PA</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Final Rank</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const teams = [...leagueInfo.teams];

                  teams.sort((a, b) => {
                    const fa = a.finalStanding || null;
                    const fb = b.finalStanding || null;
                    if (fa && fb) return fa - fb;

                    const aWins = a.wins ?? 0;
                    const bWins = b.wins ?? 0;
                    if (bWins !== aWins) return bWins - aWins;

                    const aLoss = a.losses ?? 0;
                    const bLoss = b.losses ?? 0;
                    if (aLoss !== bLoss) return aLoss - bLoss;

                    const aPF = a.pointsFor ?? 0;
                    const bPF = b.pointsFor ?? 0;
                    return bPF - aPF;
                  });

                  return teams.map((t, idx) => (
                    <tr key={t.teamId ?? idx}>
                      <td style={tdStyle}>{idx + 1}</td>
                      <td style={{ ...tdStyle, fontWeight: 600 }}>
                        {t.teamName}
                      </td>
                      <td style={tdStyle}>{t.owners}</td>
                      <td style={tdStyle}>
                        {t.wins}–{t.losses}
                        {t.ties ? `–${t.ties}` : ""}
                      </td>
                      <td style={tdStyle}>
                        {typeof t.pointsFor === "number"
                          ? t.pointsFor.toFixed(1)
                          : "-"}
                      </td>
                      <td style={tdStyle}>
                        {typeof t.pointsAgainst === "number"
                          ? t.pointsAgainst.toFixed(1)
                          : "-"}
                      </td>
                      <td style={tdStyle}>
                        {t.finalStanding ? t.finalStanding : "-"}
                      </td>
                    </tr>
                  ));
                })()}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );

  // ----- Dashboard Tab -----
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
          {dashboardMode === "weekly" &&
            sortedWeekTeams.length > 0 &&
            (() => {
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
                        const z = leader?.perCategoryZ?.[catKey] ?? 0;
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

          {dashboardMode === "season" &&
            sortedSeasonTeams.length > 0 &&
            (() => {
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

          {dashboardMode === "team_history" &&
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

        {/* Main table area */}
        <section
          style={{
            marginBottom: "24px",
            padding: "16px",
            borderRadius: "12px",
            background: "rgba(15,23,42,0.9)",
            boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
          }}
        >
          {dashboardMode === "weekly" && (
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
                        <SortHeader
                          label="Rank"
                          field="RANK"
                          sortField={sortField}
                          sortDirection={sortDirection}
                          onSort={handleSort}
                        />
                        <SortHeader
                          label="Team"
                          field="TEAM_NAME"
                          sortField={sortField}
                          sortDirection={sortDirection}
                          onSort={handleSort}
                        />
                        <SortHeader
                          label="Total Z"
                          field="TOTAL_Z"
                          sortField={sortField}
                          sortDirection={sortDirection}
                          onSort={handleSort}
                        />
                        {CATEGORIES.map((cat) => (
                          <SortHeader
                            key={cat}
                            label={cat}
                            field={cat}
                            sortField={sortField}
                            sortDirection={sortDirection}
                            onSort={handleSort}
                          />
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

          {dashboardMode === "season" && (
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
                        <SortHeader
                          label="Rank"
                          field="RANK"
                          sortField={sortField}
                          sortDirection={sortDirection}
                          onSort={handleSort}
                        />
                        <SortHeader
                          label="Team"
                          field="TEAM_NAME"
                          sortField={sortField}
                          sortDirection={sortDirection}
                          onSort={handleSort}
                        />
                        <th style={thStyle}>Weeks</th>
                        <SortHeader
                          label="Avg Total Z"
                          field="AVG_TOTAL_Z"
                          sortField={sortField}
                          sortDirection={sortDirection}
                          onSort={handleSort}
                        />
                        <SortHeader
                          label="Sum Total Z"
                          field="SUM_TOTAL_Z"
                          sortField={sortField}
                          sortDirection={sortDirection}
                          onSort={handleSort}
                        />
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

          {dashboardMode === "team_history" && (
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
                            <th style={{ ...thStyle, cursor: "default" }}>
                              Week
                            </th>
                            <th style={{ ...thStyle, cursor: "default" }}>
                              Total Z
                            </th>
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
                            const weekNo = entry.week;
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
                                <tr key={weekNo}>
                                  <td style={tdStyle}>{weekNo}</td>
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
                                <tr key={weekNo}>
                                  <td style={tdStyle}>{weekNo}</td>
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

  // ----- History Tab -----
  const renderHistoryTab = () => {
    if (historyMode === "awards") {
      return (
        <>
          <section
            style={{
              marginBottom: "16px",
              padding: "16px",
              borderRadius: "12px",
              background: "rgba(15,23,42,0.9)",
              boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
            }}
          >
            <h2 style={{ marginTop: 0, fontSize: "1.2rem" }}>
              Awards · By Season
            </h2>
            <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
              Computed from season power rankings for each available year.
              Champion / runner-up / last place are based on season rank;
              best/worst Z metrics are based on avg and total Z-score.
            </p>

            {loadingAwards && <div>Loading awards across seasons…</div>}

            {!loadingAwards && awardsByYear.length === 0 && (
              <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
                No award data available yet. Check that season stats exist for
                at least one year.
              </div>
            )}

            {!loadingAwards && awardsByYear.length > 0 && (
              <div style={{ overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: "0.85rem",
                  }}
                >
                  <thead>
                    <tr>
                      <th style={{ ...thStyle, cursor: "default" }}>Year</th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Champion
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>2nd</th>
                      <th style={{ ...thStyle, cursor: "default" }}>3rd</th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Last Place
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Best Avg Z
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Worst Avg Z
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Best Total Z
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Worst Total Z
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {awardsByYear.map((row) => (
                      <tr key={row.year}>
                        <td style={tdStyle}>{row.year}</td>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>
                          {row.champion}
                        </td>
                        <td style={tdStyle}>{row.second}</td>
                        <td style={tdStyle}>{row.third}</td>
                        <td style={tdStyle}>{row.last}</td>
                        <td style={tdStyle}>
                          {row.bestAvgZ
                            ? `${row.bestAvgZ.team} (${row.bestAvgZ.value.toFixed(
                                2
                              )})`
                            : "-"}
                        </td>
                        <td style={tdStyle}>
                          {row.worstAvgZ
                            ? `${row.worstAvgZ.team} (${row.worstAvgZ.value.toFixed(
                                2
                              )})`
                            : "-"}
                        </td>
                        <td style={tdStyle}>
                          {row.bestTotalZ
                            ? `${row.bestTotalZ.team} (${row.bestTotalZ.value.toFixed(
                                2
                              )})`
                            : "-"}
                        </td>
                        <td style={tdStyle}>
                          {row.worstTotalZ
                            ? `${row.worstTotalZ.team} (${row.worstTotalZ.value.toFixed(
                                2
                              )})`
                            : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      );
    }

    // historyMode === "team_history"
    return (
      <>
        <section
          style={{
            marginBottom: "16px",
            padding: "16px",
            borderRadius: "12px",
            background: "rgba(15,23,42,0.9)",
            boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
          }}
        >
          <h2 style={{ marginTop: 0, fontSize: "1.2rem" }}>
            Team History · Across All Seasons
          </h2>
          <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
            Aggregated from season power rankings across all available years.
            Average rank, best/worst finish, and Z-score metrics are based on
            league power rather than ESPN playoff results.
          </p>

          {loadingAwards && <div>Loading multi-season history…</div>}

          {!loadingAwards &&
            (!multiSeasonTeams || multiSeasonTeams.length === 0) && (
              <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
                No multi-season data yet. Once at least one season has power
                stats, this table will populate.
              </div>
            )}

          {!loadingAwards &&
            multiSeasonTeams &&
            multiSeasonTeams.length > 0 && (
              <div style={{ overflowX: "auto" }}>
                <table
                  style={{
                    width: "100%",
                    borderCollapse: "collapse",
                    fontSize: "0.85rem",
                  }}
                >
                  <thead>
                    <tr>
                      <th style={{ ...thStyle, cursor: "default" }}>Team</th>
                      <th style={{ ...thStyle, cursor: "default" }}>Seasons</th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Avg Rank
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Best Finish
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Worst Finish
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Avg Z (Across Seasons)
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Best Avg Z (Year)
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Worst Avg Z (Year)
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Best Total Z (Year)
                      </th>
                      <th style={{ ...thStyle, cursor: "default" }}>
                        Worst Total Z (Year)
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {multiSeasonTeams.map((t) => (
                      <tr key={t.teamName}>
                        <td style={{ ...tdStyle, fontWeight: 600 }}>
                          {t.teamName}
                        </td>
                        <td style={tdStyle}>{t.seasons}</td>
                        <td style={tdStyle}>
                          {t.avgRank != null ? t.avgRank.toFixed(2) : "-"}
                        </td>
                        <td style={tdStyle}>
                          {t.bestFinish != null ? t.bestFinish : "-"}
                        </td>
                        <td style={tdStyle}>
                          {t.worstFinish != null ? t.worstFinish : "-"}
                        </td>
                        <td style={tdStyle}>
                          {t.avgZAcrossSeasons.toFixed(2)}
                        </td>
                        <td style={tdStyle}>
                          {t.bestAvgZ
                            ? `${t.bestAvgZ.year} (${t.bestAvgZ.value.toFixed(
                                2
                              )})`
                            : "-"}
                        </td>
                        <td style={tdStyle}>
                          {t.worstAvgZ
                            ? `${t.worstAvgZ.year} (${t.worstAvgZ.value.toFixed(
                                2
                              )})`
                            : "-"}
                        </td>
                        <td style={tdStyle}>
                          {t.bestTotalZ
                            ? `${t.bestTotalZ.year} (${t.bestTotalZ.value.toFixed(
                                2
                              )})`
                            : "-"}
                        </td>
                        <td style={tdStyle}>
                          {t.worstTotalZ
                            ? `${t.worstTotalZ.year} (${t.worstTotalZ.value.toFixed(
                                2
                              )})`
                            : "-"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
        </section>
      </>
    );
  };

  // ----- Render root -----

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

      {loadingMeta && (
        <div style={{ marginBottom: "16px" }}>
          Loading league metadata…
        </div>
      )}

      {!loadingMeta && tab === "overview" && renderOverviewTab()}
      {!loadingMeta && tab === "dashboard" && renderDashboardTab()}
      {!loadingMeta && tab === "history" && renderHistoryTab()}
    </div>
  );
}

export default App;