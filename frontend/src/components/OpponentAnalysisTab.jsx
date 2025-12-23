import { useEffect, useMemo, useState } from "react";
import { getOpponentMatrixMulti, getAnalysisHealth } from "../api/client";
import { thStyle, tdStyle } from "../ui/table";

const METRIC_MODES = [
  { id: "catWinPct", label: "Category Win % vs Opponents" },
  { id: "zDiff", label: "Z-Score Edge (H2H)" },
  { id: "recordWinPct", label: "Matchup Record Win %" },
];

function clamp01(v) {
  if (v == null || Number.isNaN(v)) return 0.5;
  return Math.min(1, Math.max(0, v));
}

function formatPct(v) {
  if (v == null || Number.isNaN(v)) return "-";
  return `${Math.round(v * 100)}%`;
}

function formatZ(v) {
  if (v == null || Number.isNaN(v)) return "-";
  return v.toFixed(2);
}

function flatten(arr) {
  return arr.reduce((acc, row) => acc.concat(row), []);
}

function getHeatColor(value, mode, stats) {
  if (value == null || Number.isNaN(value)) return "transparent";

  if (mode === "zDiff") {
    const maxAbs = stats.maxAbs || 1;
    const norm = Math.min(Math.abs(value) / maxAbs, 1);
    const alpha = 0.15 + 0.6 * norm;

    if (value >= 0) return `rgba(34,197,94,${alpha})`;
    return `rgba(239,68,68,${alpha})`;
  }

  const v = clamp01(value);
  const center = 0.5;

  if (v === center) return "transparent";

  if (v > center) {
    const norm = (v - center) / (1 - center);
    const alpha = 0.15 + 0.6 * norm;
    return `rgba(34,197,94,${alpha})`;
  } else {
    const norm = (center - v) / center;
    const alpha = 0.15 + 0.6 * norm;
    return `rgba(248,113,113,${alpha})`;
  }
}

export default function OpponentAnalysisTab({
  year,
  availableYears,
  seasonPower,
  selectedTeamId,
  onChangeTeam,
  categories,
}) {
  const teams = seasonPower?.teams || [];

  const [metricMode, setMetricMode] = useState("catWinPct");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // health
  const [health, setHealth] = useState(null);
  const [healthError, setHealthError] = useState(null);

  const [minYear, setMinYear] = useState(null);
  const [maxYear, setMaxYear] = useState(null);
  const [ownerEraOnly, setOwnerEraOnly] = useState(true);

  const teamOptions = useMemo(() => {
    if (!teams.length) return [];
    const copy = [...teams];
    copy.sort((a, b) => {
      const ar = a.rank ?? 999;
      const br = b.rank ?? 999;
      return ar - br;
    });
    return copy;
  }, [teams]);

  const selectedTeam =
    teamOptions.find((t) => t.teamId === selectedTeamId) || null;

  const yearRange = useMemo(() => {
    if (Array.isArray(availableYears) && availableYears.length) {
      return [...availableYears].sort((a, b) => a - b);
    }
    const latest = year || new Date().getFullYear();
    const first = 2019;
    const out = [];
    for (let y = first; y <= latest; y += 1) out.push(y);
    return out;
  }, [availableYears, year]);

  useEffect(() => {
    if (!yearRange.length) return;

    const defaultMin = 2019;
    const defaultMax = yearRange[yearRange.length - 1];

    setMinYear((prev) => {
      if (prev == null) return defaultMin;
      if (prev < defaultMin) return defaultMin;
      if (prev > defaultMax) return defaultMax;
      return prev;
    });

    setMaxYear((prev) => {
      if (prev == null) return defaultMax;
      if (prev < defaultMin) return defaultMin;
      if (prev > defaultMax) return defaultMax;
      return prev;
    });
  }, [yearRange]);

  // -------- health fetch --------
  useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      try {
        setHealthError(null);
        const h = await getAnalysisHealth(year);
        if (!cancelled) setHealth(h);
      } catch (e) {
        if (!cancelled) setHealthError(String(e?.message || e));
      }
    }

    if (year) loadHealth();

    return () => {
      cancelled = true;
    };
  }, [year]);

  const healthBanner = useMemo(() => {
    if (healthError) {
      return (
        <div style={{ marginBottom: 12, color: "#fca5a5", fontSize: "0.9rem" }}>
          Health check failed: {healthError}
        </div>
      );
    }

    if (!health) return null;

    const latestWeek = health.latestWeek;
    const oppRows = health.counts?.opponentMatrixAggYear ?? 0;

    if (!latestWeek) {
      return (
        <div style={{ marginBottom: 12, color: "#fbbf24", fontSize: "0.9rem" }}>
          No completed weeks found for {year} yet (latestWeek is null). Opponent
          matrix will be empty.
        </div>
      );
    }

    if (oppRows === 0) {
      return (
        <div style={{ marginBottom: 12, color: "#fbbf24", fontSize: "0.9rem" }}>
          Opponent matrix agg table has 0 rows for {year}. Rebuild it:
          <code style={{ marginLeft: 8 }}>
            python -m scripts.rebuild_opponent_matrix_agg_year --year {year} --force
          </code>
        </div>
      );
    }

    return null;
  }, [health, healthError, year]);

  const effectiveCategories = useMemo(() => categories || [], [categories]);

  const minYearOptions = useMemo(() => {
    if (!yearRange.length) return [];
    if (!maxYear) return yearRange;
    return yearRange.filter((y) => y <= maxYear);
  }, [yearRange, maxYear]);

  const maxYearOptions = useMemo(() => {
    if (!yearRange.length) return [];
    if (!minYear) return yearRange;
    return yearRange.filter((y) => y >= minYear);
  }, [yearRange, minYear]);

  useEffect(() => {
    if (selectedTeamId || !teamOptions.length) return;
    const first = teamOptions[0];
    if (first?.teamId && onChangeTeam) onChangeTeam(first.teamId);
  }, [teamOptions, selectedTeamId, onChangeTeam]);

  // -------- opponent matrix fetch --------
  useEffect(() => {
    if (!selectedTeamId || !minYear || !maxYear) {
      setData(null);
      return;
    }

    let cancelled = false;

    const run = async () => {
      setLoading(true);
      setError("");
      try {
        const payload = await getOpponentMatrixMulti(
          minYear,
          maxYear,
          selectedTeamId,
          ownerEraOnly,
          false,
        );
        if (cancelled) return;
        setData(payload);
      } catch (e) {
        console.error("Opponent matrix error:", e);
        if (cancelled) return;
        setError(e.message || "Failed to load opponent analysis");
        setData(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    run();

    return () => {
      cancelled = true;
    };
  }, [selectedTeamId, minYear, maxYear, ownerEraOnly]);

  const {
    opponents,
    rowLabels,
    values,
    colorMode,
    recordByOpponent,
    rangeLabel,
  } = useMemo(() => {
    const empty = {
      opponents: [],
      rowLabels: [],
      values: [],
      colorMode: metricMode === "zDiff" ? "zDiff" : "winPct",
      recordByOpponent: {},
      rangeLabel: "",
    };

    if (
      !data ||
      !Array.isArray(data.rows) ||
      !data.rows.length ||
      !effectiveCategories.length
    ) {
      return empty;
    }

    const rows = data.rows;
    const oppNames = rows.map((r) => r.opponentName);

    const label =
      data.minYear && data.maxYear
        ? `${data.minYear}–${data.maxYear}`
        : data.year
        ? String(data.year)
        : "";

    const recordMap = {};
    rows.forEach((r) => {
      const overall = r.overall || {};
      const wins = overall.wins ?? 0;
      const losses = overall.losses ?? 0;
      const ties = overall.ties ?? 0;
      const total = wins + losses + ties || 1;
      const winPct =
        typeof overall.winPct === "number"
          ? overall.winPct
          : (wins + 0.5 * ties) / total;

      recordMap[r.opponentName] = {
        wins,
        losses,
        ties,
        winPct,
        matchups: r.matchups ?? total,
      };
    });

    if (metricMode === "catWinPct") {
      const vals = effectiveCategories.map((cat) =>
        rows.map((r) => {
          const catStats = r.categories?.[cat];
          if (!catStats) return 0.5;
          const wp = catStats.winPct;
          return typeof wp === "number" ? wp : 0.5;
        }),
      );

      return {
        opponents: oppNames,
        rowLabels: effectiveCategories,
        values: vals,
        colorMode: "winPct",
        recordByOpponent: recordMap,
        rangeLabel: label,
      };
    }

    if (metricMode === "zDiff") {
      const diffMatrix = effectiveCategories.map((cat) =>
        rows.map((r) => {
          const catStats = r.categories?.[cat];
          const diff = catStats?.avgDiff;
          return typeof diff === "number" ? diff : 0.0;
        }),
      );

      const zMatrix = diffMatrix.map((row) => {
        const valid = row.filter((v) => !Number.isNaN(v));
        if (!valid.length) return row.map(() => 0.0);

        const mean = valid.reduce((s, v) => s + v, 0) / valid.length;
        const variance =
          valid.reduce((s, v) => s + (v - mean) * (v - mean), 0) /
            valid.length || 0;
        const std = Math.sqrt(variance) || 1;

        return row.map((v) => (v - mean) / std);
      });

      return {
        opponents: oppNames,
        rowLabels: effectiveCategories,
        values: zMatrix,
        colorMode: "zDiff",
        recordByOpponent: recordMap,
        rangeLabel: label,
      };
    }

    if (metricMode === "recordWinPct") {
      const vals = [
        rows.map((r) => {
          const overall = r.overall || {};
          const wins = overall.wins ?? 0;
          const losses = overall.losses ?? 0;
          const ties = overall.ties ?? 0;
          const total = wins + losses + ties || 1;
          if (typeof overall.winPct === "number") return overall.winPct;
          return (wins + 0.5 * ties) / total;
        }),
      ];

      return {
        opponents: oppNames,
        rowLabels: ["Record"],
        values: vals,
        colorMode: "winPct",
        recordByOpponent: recordMap,
        rangeLabel: label,
      };
    }

    return empty;
  }, [data, metricMode, effectiveCategories]);

  const hasMatrix =
    opponents.length > 0 && values.length > 0 && values[0].length > 0;

  const stats = useMemo(() => {
    if (!values.length) return { min: 0, max: 1, maxAbs: 1 };
    const flat = flatten(values).filter(
      (v) => typeof v === "number" && !Number.isNaN(v),
    );
    if (!flat.length) return { min: 0, max: 1, maxAbs: 1 };
    const minVal = Math.min(...flat);
    const maxVal = Math.max(...flat);
    const maxAbs = Math.max(Math.abs(minVal), Math.abs(maxVal), 0.1);
    return { min: minVal, max: maxVal, maxAbs };
  }, [values]);

  const renderTeamSelector = () => {
    if (!teamOptions.length) {
      return (
        <div style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
          No season power data loaded yet.
        </div>
      );
    }

    return (
      <label
        style={{
          fontSize: "0.8rem",
          display: "flex",
          flexDirection: "column",
          gap: "4px",
        }}
      >
        Team
        <select
          value={selectedTeamId || ""}
          onChange={(e) => {
            const val = e.target.value ? Number(e.target.value) : null;
            onChangeTeam?.(val);
          }}
          style={{
            display: "block",
            marginTop: "4px",
            padding: "4px 8px",
            borderRadius: "6px",
            border: "1px solid #334155",
            background: "#020617",
            color: "#e5e7eb",
            minWidth: "200px",
          }}
        >
          <option value="">Select a team…</option>
          {teamOptions.map((t) => (
            <option key={t.teamId} value={t.teamId}>
              {t.rank ? `#${t.rank} · ` : ""}
              {t.teamName}
            </option>
          ))}
        </select>
      </label>
    );
  };

  if (!selectedTeamId) {
    return (
      <div style={{ padding: "16px" }}>
        <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "8px" }}>
          Opponent Analysis · {year}
        </h2>
        {healthBanner}
        {renderTeamSelector()}
        <div style={{ marginTop: "12px", fontSize: "0.8rem", color: "#9ca3af" }}>
          Pick a team to see head-to-head category and record edges vs each
          opponent.
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: "16px" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          gap: "16px",
          marginBottom: "16px",
          flexWrap: "wrap",
        }}
      >
        <div>
          <h2 style={{ fontSize: "1rem", fontWeight: 600, marginBottom: "4px" }}>
            Opponent Analysis ·{" "}
            {selectedTeam?.teamName || `Team ${selectedTeamId}`}{" "}
            {rangeLabel ? `· ${rangeLabel}` : ""}
          </h2>
          <p style={{ fontSize: "0.75rem", color: "#9ca3af" }}>
            Head-to-head only – weeks where these teams actually played within
            the selected seasons.
          </p>
        </div>

        <div
          style={{
            display: "flex",
            gap: "12px",
            alignItems: "flex-end",
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", fontSize: "0.8rem", gap: "4px" }}>
            <span>Years</span>
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
              <select
                value={minYear || ""}
                onChange={(e) => {
                  const val = e.target.value ? Number(e.target.value) : null;
                  if (val == null) return;
                  setMinYear(val);
                  if (maxYear && val > maxYear) setMaxYear(val);
                }}
                style={{
                  padding: "4px 8px",
                  borderRadius: "6px",
                  border: "1px solid #334155",
                  background: "#020617",
                  color: "#e5e7eb",
                  minWidth: "90px",
                }}
              >
                {minYearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
              <span style={{ color: "#64748b" }}>–</span>
              <select
                value={maxYear || ""}
                onChange={(e) => {
                  const val = e.target.value ? Number(e.target.value) : null;
                  if (val == null) return;
                  setMaxYear(val);
                  if (minYear && val < minYear) setMinYear(val);
                }}
                style={{
                  padding: "4px 8px",
                  borderRadius: "6px",
                  border: "1px solid #334155",
                  background: "#020617",
                  color: "#e5e7eb",
                  minWidth: "90px",
                }}
              >
                {maxYearOptions.map((y) => (
                  <option key={y} value={y}>
                    {y}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <label style={{ fontSize: "0.8rem", display: "flex", flexDirection: "column", gap: "4px" }}>
            Metric
            <select
              value={metricMode}
              onChange={(e) => setMetricMode(e.target.value)}
              style={{
                marginTop: "4px",
                padding: "4px 8px",
                borderRadius: "6px",
                border: "1px solid #334155",
                background: "#020617",
                color: "#e5e7eb",
                minWidth: "200px",
              }}
            >
              {METRIC_MODES.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          </label>

          {renderTeamSelector()}

          <label
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              fontSize: "0.8rem",
              cursor: "pointer",
              whiteSpace: "nowrap",
            }}
          >
            <input
              type="checkbox"
              checked={ownerEraOnly}
              onChange={(e) => setOwnerEraOnly(e.target.checked)}
              style={{ cursor: "pointer" }}
            />
            <span>Current owner era only</span>
          </label>
        </div>
      </header>

      {healthBanner}

      {loading && (
        <div style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
          Loading opponent analysis…
        </div>
      )}

      {error && (
        <div style={{ fontSize: "0.8rem", color: "#f97373", marginBottom: "8px" }}>
          {error}
        </div>
      )}

      {!loading && !error && !hasMatrix && (
        <div style={{ fontSize: "0.8rem", color: "#9ca3af" }}>
          No opponent data available for this selection.
        </div>
      )}

      {!loading && !error && hasMatrix && (
        <>
          <div
            style={{
              overflowX: "auto",
              borderRadius: "8px",
              border: "1px solid #1f2933",
              marginBottom: "8px",
            }}
          >
            <table
              style={{
                borderCollapse: "collapse",
                width: "100%",
                minWidth: "600px",
                fontSize: "0.75rem",
              }}
            >
              <thead>
                <tr>
                  <th
                    style={{
                      ...thStyle,
                      position: "sticky",
                      left: 0,
                      zIndex: 2,
                      background: "#020617",
                    }}
                  >
                    {metricMode === "recordWinPct" ? "Metric" : "Category"}
                  </th>
                  {opponents.map((oppName, idx) => (
                    <th key={idx} style={thStyle}>
                      {oppName}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rowLabels.map((label, rowIdx) => {
                  const row = values[rowIdx] || [];
                  return (
                    <tr key={label}>
                      <td
                        style={{
                          ...tdStyle,
                          position: "sticky",
                          left: 0,
                          zIndex: 1,
                          background: "#020617",
                          fontWeight: 600,
                        }}
                      >
                        {label}
                      </td>
                      {row.map((val, colIdx) => {
                        const bg = getHeatColor(val, colorMode, stats);
                        const title =
                          colorMode === "zDiff"
                            ? `${label} vs ${opponents[colIdx]}: ${formatZ(val)}`
                            : `${label} vs ${opponents[colIdx]}: ${formatPct(val)}`;
                        return (
                          <td
                            key={colIdx}
                            title={title}
                            style={{
                              ...tdStyle,
                              background: bg,
                              color: "#f9fafb",
                              textAlign: "center",
                              fontWeight: 600,
                              whiteSpace: "nowrap",
                            }}
                          >
                            {colorMode === "zDiff" ? formatZ(val) : formatPct(val)}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: "6px", fontSize: "0.7rem", color: "#9ca3af" }}>
            {colorMode === "zDiff" ? (
              <div>
                Color scale: negative z (red) = they’ve outplayed you; positive z
                (green) = you’ve outplayed them, based on per-category head-to-head
                score differences.
              </div>
            ) : (
              <div>Color scale: red = low win%, green = high win%, neutral ≈ 50%.</div>
            )}

            {Object.keys(recordByOpponent).length > 0 && (
              <div>
                Matchup summary (W–L–T, win%) for the selected seasons:
                <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 16px", marginTop: "4px" }}>
                  {opponents.map((opp) => {
                    const rec = recordByOpponent[opp];
                    if (!rec) return null;
                    return (
                      <div key={opp} style={{ color: "#cbd5f5" }}>
                        <span style={{ color: "#9ca3af" }}>{opp}:</span>{" "}
                        {rec.wins}-{rec.losses}
                        {rec.ties ? `-${rec.ties}` : ""} ({formatPct(rec.winPct)})
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}