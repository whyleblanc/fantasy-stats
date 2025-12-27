// frontend/src/components/AwardsTab.jsx
import { useEffect, useMemo, useRef, useState } from "react";
import { getAwards } from "../api/client";

export default function AwardsTab({ metaYears = [], seasonPower = null }) {
  // ----------------------------
  // Filters
  // ----------------------------
  const [scope, setScope] = useState("league"); // league | team | owner
  const [mode, setMode] = useState("summary"); // summary | year_by_year
  const [year, setYear] = useState("all_time"); // all_time | "2026"
  const [teamId, setTeamId] = useState("");
  const [ownerCode, setOwnerCode] = useState("");
  const [currentOwnerEraOnly, setCurrentOwnerEraOnly] = useState(true);

  // Cache owners so Owner dropdown can populate even before first owner query
  const [ownersCache, setOwnersCache] = useState([]);

  // ----------------------------
  // Data
  // ----------------------------
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [showLoading, setShowLoading] = useState(false);
  const [err, setErr] = useState(null);

  // ----------------------------
  // Collapses
  // ----------------------------
  const [openWeek, setOpenWeek] = useState(true);
  const [openSeason, setOpenSeason] = useState(true);
  const [openCatWeek, setOpenCatWeek] = useState(false);
  const [openCatSeason, setOpenCatSeason] = useState(false);
  const [openLuck, setOpenLuck] = useState(true);

  // Request sequencing guard (prevents stale fetches toggling loading/data)
  const reqSeq = useRef(0);

  // Year-by-year selector (only used when mode=year_by_year)
  const [selectedYBYYear, setSelectedYBYYear] = useState("");

  // ----------------------------
  // Derived: teams / owners / yearsAvailable
  // ----------------------------
  const teams = useMemo(() => {
    const list = seasonPower?.teams || [];
    return [...list].sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
  }, [seasonPower]);

  const owners = useMemo(() => {
    const live = data?.owners;
    if (Array.isArray(live) && live.length) return live;
    return ownersCache;
  }, [data?.owners, ownersCache]);

  const yearsAvailable = useMemo(() => {
    if (Array.isArray(metaYears) && metaYears.length) return metaYears;
    const fallback = data?.meta?.yearsAvailable;
    return Array.isArray(fallback) ? fallback : [];
  }, [metaYears, data?.meta?.yearsAvailable]);

  // For year_by_year mode, these are the years actually present in the payload objects
  const ybyYears = useMemo(() => {
    // use meta years (stable), not award keys (shape varies and can be empty)
    const ys = yearsAvailable;
    if (!Array.isArray(ys)) return [];
    return ys.map(String).sort((a, b) => Number(b) - Number(a));
  }, [yearsAvailable]);

  // When year-by-year data arrives, default the selector to the newest year
  useEffect(() => {
    if (mode !== "year_by_year") return;
    if (selectedYBYYear) return;
    if (ybyYears.length) setSelectedYBYYear(String(ybyYears[0]));
  }, [mode, ybyYears, selectedYBYYear]);

  useEffect(() => {
  if (mode !== "year_by_year") {
    setSelectedYBYYear("");
    return;
  }
  // if user picked a specific year (not all_time), lock selector to that year
  if (String(year) !== "all_time") {
    setSelectedYBYYear(String(year));
  }
}, [mode, year]);

  // Cache owners from any successful response
  useEffect(() => {
    if (Array.isArray(data?.owners) && data.owners.length) {
      setOwnersCache(data.owners);
    }
  }, [data]);

  // Delay loading indicator to prevent flicker
  useEffect(() => {
    if (!loading) {
      setShowLoading(false);
      return;
    }
    const t = setTimeout(() => setShowLoading(true), 150);
    return () => clearTimeout(t);
  }, [loading]);

  // ----------------------------
  // Scope change cleanup + auto-picks
  // ----------------------------
  useEffect(() => {
    if (scope === "league") {
      setTeamId("");
      setOwnerCode("");
      return;
    }

    if (scope === "team") {
      setOwnerCode("");
      setTeamId((prev) => prev || (teams.length ? String(teams[0].teamId) : ""));
      return;
    }

    if (scope === "owner") {
      setTeamId("");
      setOwnerCode((prev) => prev || (ownersCache.length ? ownersCache[0].ownerCode : ""));
      return;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, teams]);

  useEffect(() => {
  // League scope only supports summary in the UI
  if (scope === "league" && mode !== "summary") {
    setMode("summary");
  }
  }, [scope, mode]);

  // ----------------------------
  // Fetch awards whenever filters change
  // ----------------------------
  useEffect(() => {
    let cancelled = false;
    const myReq = ++reqSeq.current;

    const setLoadingSafe = (v) => {
      if (!cancelled && myReq === reqSeq.current) setLoading(v);
    };
    const setErrSafe = (v) => {
      if (!cancelled && myReq === reqSeq.current) setErr(v);
    };
    const setDataSafe = (v) => {
      if (!cancelled && myReq === reqSeq.current) setData(v);
    };

    const run = async () => {
      // TEAM: wait until teamId exists
      if (scope === "team" && !teamId) {
        setDataSafe(null);
        setErrSafe(null);
        setLoadingSafe(false);
        return;
      }

      // OWNER: if no ownerCode, try to prime owners first (league fetch)
      if (scope === "owner" && !ownerCode) {
        if (ownersCache.length) {
          // This will trigger the effect again with ownerCode set
          setOwnerCode(ownersCache[0].ownerCode);
          return;
        }

        setLoadingSafe(true);
        setErrSafe(null);

        try {
          const prime = await getAwards({
            scope: "league",
            mode: "summary",
            year,
            currentOwnerEraOnly: true,
          });

          if (cancelled || myReq !== reqSeq.current) return;

          if (Array.isArray(prime?.owners) && prime.owners.length) {
            setOwnersCache(prime.owners);
            setOwnerCode(prime.owners[0].ownerCode);
          }
        } catch (e) {
          if (cancelled || myReq !== reqSeq.current) return;
          console.error(e);
          setErrSafe(e?.message || "Awards fetch failed");
        } finally {
          setLoadingSafe(false);
        }
        return;
      }

      setLoadingSafe(true);
      setErrSafe(null);

      try {
        const payload = await getAwards({
          scope,
          mode,
          year,
          teamId: scope === "team" ? Number(teamId) : null,
          ownerCode: scope === "owner" ? ownerCode : null,
          currentOwnerEraOnly,
        });

        if (cancelled || myReq !== reqSeq.current) return;
        setDataSafe(payload);
      } catch (e) {
        if (cancelled || myReq !== reqSeq.current) return;
        console.error(e);
        setErrSafe(e?.message || "Awards fetch failed");
        setDataSafe(null);
      } finally {
        setLoadingSafe(false);
      }
    };

    run();
    return () => {
      cancelled = true;
    };
  }, [scope, mode, year, teamId, ownerCode, currentOwnerEraOnly]);
  
  useEffect(() => {
    setErr(null);
  }, [mode, year, scope, teamId, ownerCode, currentOwnerEraOnly]);

  // ----------------------------
  // Formatting helpers
  // ----------------------------
  const fmt = (v, d = 3) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return null;
    return n.toFixed(d);
  };

  const fmtPct = (v, d = 1) => {
    const n = Number(v);
    if (!Number.isFinite(n)) return null;
    return `${(n * 100).toFixed(d)}%`;
  };

  const isPctCat = (awardId = "") => {
    const s = String(awardId).toLowerCase();
    return s.includes("_fg_") || s.includes("_ft_");
  };

  const fmtRaw = (rawValue, awardId) => {
    const n = Number(rawValue);
    if (!Number.isFinite(n)) return null;
    if (isPctCat(awardId)) return fmtPct(n, 3);
    return n.toFixed(3);
  };

  // ----------------------------
  // Rendering helpers
  // ----------------------------
  const renderWinners = (awardId, winners = []) => {
    if (!Array.isArray(winners) || winners.length === 0) {
      return <div style={{ color: "#94a3b8" }}>No winners</div>;
    }

    return (
      <div style={{ display: "grid", gap: 6 }}>
        {winners.map((w, idx) => {
          const z = fmt(w?.value, 3);
          const raw = fmtRaw(w?.rawValue, awardId);
          const when = w.week != null ? `${w.year} W${w.week}` : `${w.year}`;

          // Luck awards may include these fields; show if present
          const hasLuckContext = w.actualWinPct != null && w.expectedWinPct != null;
          const actualPct = hasLuckContext ? fmtPct(w.actualWinPct, 1) : null;
          const expectedPct = hasLuckContext ? fmtPct(w.expectedWinPct, 1) : null;

          return (
            <div
              key={`${w.year}-${w.week ?? "S"}-${w.teamId}-${idx}`}
              style={{ display: "flex", gap: 10, alignItems: "baseline" }}
            >
              <span style={{ color: "#94a3b8", minWidth: 90 }}>{when}</span>

              <span style={{ flex: 1 }}>
                {w.teamName}
                {hasLuckContext && (
                  <span style={{ color: "#94a3b8", fontSize: 12, marginLeft: 10 }}>
                    actual {actualPct} · expected {expectedPct}
                  </span>
                )}
              </span>

              <span style={{ fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>
                {raw != null ? `${raw} · Z ${z}` : `Z ${z}`}
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  const renderSection = (title, list, open, setOpen) => {
    const count = Array.isArray(list) ? list.length : 0;

    return (
      <div style={{ marginTop: 14 }}>
        <button
          onClick={() => setOpen(!open)}
          style={{
            width: "100%",
            textAlign: "left",
            border: "1px solid #1f2937",
            borderRadius: 12,
            padding: "10px 12px",
            background: "rgba(2,6,23,0.55)",
            color: "#e5e7eb",
            cursor: "pointer",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 12,
          }}
        >
          <span style={{ fontWeight: 800 }}>{title}</span>
          <span style={{ color: "#94a3b8", fontSize: 12 }}>
            {count} awards {open ? "▾" : "▸"}
          </span>
        </button>

        {open && (
          <div style={{ marginTop: 10, display: "grid", gap: 10 }}>
            {(list || []).map((a) => (
              <div
                key={a.id}
                style={{
                  border: "1px solid #1f2937",
                  borderRadius: 12,
                  padding: 12,
                  background: "rgba(2,6,23,0.35)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
                  <div style={{ fontWeight: 800 }}>{a.label ?? a.id}</div>
                  <div style={{ color: "#94a3b8", fontSize: 12 }}>{a.id}</div>
                </div>

                <div style={{ marginTop: 10 }}>{renderWinners(a.id, a.winners)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    );
  };

  const pickYBY = (obj) => {
    if (!obj || typeof obj !== "object" || Array.isArray(obj)) return [];
    const key = selectedYBYYear || Object.keys(obj)[0];
    const list = obj[String(key)];
    return Array.isArray(list) ? list : [];
  };

  // In year_by_year mode, render ONLY selected year (prevents massive dump)
  const weekList = mode === "summary" ? data?.awards?.week : pickYBY(data?.awards?.week);
  const seasonList = mode === "summary" ? data?.awards?.season : pickYBY(data?.awards?.season);
  const catWeekList =
    mode === "summary" ? data?.awards?.category_week : pickYBY(data?.awards?.category_week);
  const catSeasonList =
    mode === "summary" ? data?.awards?.category_season : pickYBY(data?.awards?.category_season);
  const luckList = mode === "summary" ? data?.awards?.luck : pickYBY(data?.awards?.luck);

  // If year != all_time, year-by-year selector is pointless (payload only that year)
  const showYBYSelector = mode === "year_by_year" && String(year) === "all_time" && ybyYears.length > 0;

  // ----------------------------
  // Render
  // ----------------------------
  return (
    <div style={{ maxWidth: 980, margin: "0 auto" }}>
      <h2 style={{ marginTop: 0 }}>Awards</h2>

      {/* FILTER BAR */}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          alignItems: "end",
          padding: 12,
          border: "1px solid #1f2937",
          borderRadius: 12,
          marginBottom: 16,
          background: "rgba(2,6,23,0.6)",
        }}
      >
        <div>
          <label style={{ fontSize: 12, color: "#94a3b8" }}>Scope</label>
          <select value={scope} onChange={(e) => setScope(e.target.value)} style={selStyle}>
            <option value="league">League</option>
            <option value="team">Team</option>
            <option value="owner">Owner</option>
          </select>
        </div>

        <div>
          <label style={{ fontSize: 12, color: "#94a3b8" }}>Mode</label>
          <select
            value={mode}
            onChange={(e) => setMode(e.target.value)}
            style={selStyle}
            disabled={scope === "league"}
          >
            <option value="summary">Summary</option>
            {scope !== "league" && <option value="year_by_year">Year by year</option>}
          </select>
        </div>

        <div>
          <label style={{ fontSize: 12, color: "#94a3b8" }}>Year</label>
          <select value={String(year)} onChange={(e) => setYear(e.target.value)} style={selStyle}>
            <option value="all_time">All-time</option>
            {(yearsAvailable || []).map((y) => (
              <option key={y} value={String(y)}>
                {y}
              </option>
            ))}
          </select>
        </div>

        {scope === "team" && (
          <div>
            <label style={{ fontSize: 12, color: "#94a3b8" }}>Team</label>
            <select value={teamId} onChange={(e) => setTeamId(e.target.value)} style={selStyle}>
              <option value="">Select…</option>
              {teams.map((t) => (
                <option key={t.teamId} value={String(t.teamId)}>
                  {t.teamName}
                </option>
              ))}
            </select>
          </div>
        )}

        {scope === "owner" && (
          <div>
            <label style={{ fontSize: 12, color: "#94a3b8" }}>Owner</label>
            <select value={ownerCode} onChange={(e) => setOwnerCode(e.target.value)} style={selStyle}>
              <option value="">Select…</option>
              {(owners || []).map((o) => (
                <option key={o.ownerCode} value={o.ownerCode}>
                  {o.ownerCode}
                </option>
              ))}
            </select>
          </div>
        )}

        {(scope === "team" || scope === "owner") && (
          <label style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={!!currentOwnerEraOnly}
              onChange={(e) => setCurrentOwnerEraOnly(e.target.checked)}
            />
            <span style={{ color: "#cbd5e1", fontSize: 13 }}>Current owner era only</span>
          </label>
        )}
      </div>

      {/* Year-by-year selector (only when helpful) */}
      {showYBYSelector && (
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: "#94a3b8" }}>Year (Year-by-year view)</label>
          <select value={selectedYBYYear} onChange={(e) => setSelectedYBYYear(e.target.value)} style={selStyle}>
            {ybyYears.map((y) => (
              <option key={y} value={String(y)}>
                {y}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* STATUS */}
      {showLoading && <div>Loading…</div>}
      {err && <div style={{ color: "#fca5a5" }}>{err}</div>}

      {/* CONTENT */}
      {!loading && data && !err && (
        <div style={{ fontSize: 13, color: "#cbd5e1" }}>
          <div style={{ color: "#94a3b8", marginBottom: 8 }}>source: {data.source}</div>

          {renderSection("Week", weekList || [], openWeek, setOpenWeek)}
          {renderSection("Season", seasonList || [], openSeason, setOpenSeason)}
          {renderSection("Category Week", catWeekList || [], openCatWeek, setOpenCatWeek)}
          {renderSection("Category Season", catSeasonList || [], openCatSeason, setOpenCatSeason)}
          {renderSection("Luck vs Skill", luckList || [], openLuck, setOpenLuck)}
        </div>
      )}
    </div>
  );
}

const selStyle = {
  display: "block",
  marginTop: 6,
  padding: "6px 10px",
  borderRadius: 8,
  border: "1px solid #334155",
  background: "#020617",
  color: "#e5e7eb",
  minWidth: 160,
};