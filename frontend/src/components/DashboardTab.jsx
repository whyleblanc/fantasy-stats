// src/components/DashboardTab.jsx
import { useMemo, useState } from "react";
import { thStyle, tdStyle, renderZCell } from "../ui/table";
import SortHeader from "./SortHeader";

function DashboardTab({
  year,
  week,
  weekPower,
  seasonPower,
  loadingWeek,
  loadingSeason,
  categories,
}) {
  const [view, setView] = useState("weekly"); // 'weekly' | 'season'
  const [sortField, setSortField] = useState("RANK");
  const [sortDirection, setSortDirection] = useState("ASC"); // ASC = best rank first

  const weekTeams = weekPower?.teams || [];
  const seasonTeams = seasonPower?.teams || [];
  const cats = Array.isArray(categories) ? categories : [];

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === "ASC" ? "DESC" : "ASC"));
    } else {
      setSortField(field);
      // default rank sorts best → worst, others worst → best
      setSortDirection(field === "RANK" ? "ASC" : "DESC");
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
    return sortDirection === "ASC" ? na - nb : nb - na;
  };

  const sortedWeekTeams = useMemo(() => {
    if (!weekTeams.length) return [];
    const copy = [...weekTeams];

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

      // Category sort
      const key = `${sortField}_z`;
      const av = a.perCategoryZ?.[key];
      const bv = b.perCategoryZ?.[key];
      return compareNumbers(av, bv);
    });
  }, [weekTeams, sortField, sortDirection]);

  const sortedSeasonTeams = useMemo(() => {
    if (!seasonTeams.length) return [];
    const copy = [...seasonTeams];

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
  }, [seasonTeams, sortField, sortDirection]);

  return (
    <>
      {/* Local controls JUST for view/sort – no extra Year/Week here */}
      <section
        style={{
          marginBottom: "16px",
          display: "flex",
          flexWrap: "wrap",
          gap: "12px",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", flexDirection: "column" }}>
          <label style={{ fontSize: "0.9rem" }}>View</label>
          <div style={{ display: "flex", gap: 4, marginTop: 4 }}>
            {[
              { id: "weekly", label: "Weekly Power" },
              { id: "season", label: "Season Power" },
            ].map((mode) => {
              const active = view === mode.id;
              return (
                <button
                  key={mode.id}
                  onClick={() => setView(mode.id)}
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
            {view === "season" ? (
              <>
                <option value="RANK">Rank</option>
                <option value="AVG_TOTAL_Z">Avg Total Z</option>
                <option value="SUM_TOTAL_Z">Sum Total Z</option>
                <option value="TEAM_NAME">Team Name</option>
              </>
            ) : (
              <>
                <option value="RANK">Rank</option>
                <option value="TOTAL_Z">Total Z</option>
                {cats.map((c) => (
                  <option key={c} value={c}>
                    {c} Z
                  </option>
                ))}
                <option value="TEAM_NAME">Team Name</option>
              </>
            )}
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
      </section>

      {/* Table */}
      <section
        style={{
          marginBottom: "24px",
          padding: "16px",
          borderRadius: "12px",
          background: "rgba(15,23,42,0.9)",
          boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
        }}
      >
        {view === "weekly" && (
          <>
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>
              Weekly Power · {year} · Week {week}
            </h2>
            {loadingWeek && <div>Loading week data...</div>}
            {!loadingWeek && sortedWeekTeams.length === 0 && (
              <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
                No data for this week.
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
                      {cats.map((cat) => (
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
                          {cats.map((cat) => {
                            const keyName = `${cat}_z`;
                            return renderZCell(perCat[keyName] ?? 0, keyName);
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

        {view === "season" && (
          <>
            <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>
              Season Power · {year}
            </h2>
            {loadingSeason && <div>Loading season data...</div>}
            {!loadingSeason && sortedSeasonTeams.length === 0 && (
              <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
                No data for this year.
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
      </section>
    </>
  );
}

export default DashboardTab;