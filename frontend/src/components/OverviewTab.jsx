// src/components/OverviewTab.jsx
import { thStyle, tdStyle, renderZCell } from "../ui/table";

function OverviewTab({
  year,
  week,
  standingsYear,
  weekPower,
  seasonPower,
  leagueInfo,
  loadingWeek,
  loadingSeason,
  loadingLeague,
  categories,
}) {
  const weekTeams = weekPower?.teams || [];
  const seasonTeams = seasonPower?.teams || [];
  const standingsTeams = leagueInfo?.teams || [];
  const completedWeeks = leagueInfo?.completedWeeks || [];
  const currentWeek = leagueInfo?.currentWeek ?? null; // should be latest COMPLETED week
  const inProgressWeek = leagueInfo?.inProgressWeek ?? null;

  const cats = Array.isArray(categories) && categories.length ? categories : [];

  // Prefer backend rank if present; otherwise fall back to stable sort.
  const sortedStandings = (() => {
    const teams = Array.isArray(standingsTeams) ? [...standingsTeams] : [];
    if (teams.some((t) => typeof t?.rank === "number")) {
      teams.sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999));
      return teams;
    }

    // fallback: sort by matchup wins/losses, then category wins
    teams.sort((a, b) => {
      const aw = a.matchupWins ?? a.wins ?? 0;
      const bw = b.matchupWins ?? b.wins ?? 0;
      if (bw !== aw) return bw - aw;

      const al = a.matchupLosses ?? a.losses ?? 0;
      const bl = b.matchupLosses ?? b.losses ?? 0;
      if (al !== bl) return al - bl;

      const acw = a.categoryWins ?? 0;
      const bcw = b.categoryWins ?? 0;
      return bcw - acw;
    });
    return teams;
  })();

  const formatMatchupRecord = (t) => {
    if (t.matchupRecord) return t.matchupRecord;
    const w = t.matchupWins ?? t.wins ?? 0;
    const l = t.matchupLosses ?? t.losses ?? 0;
    const ti = t.matchupTies ?? t.ties ?? 0;
    return `${w}\u2013${l}${ti ? `\u2013${ti}` : ""}`;
  };

  const formatCategoryRecord = (t) => {
    if (t.categoryRecord) return t.categoryRecord;
    const w = t.categoryWins ?? 0;
    const l = t.categoryLosses ?? 0;
    const ti = t.categoryTies ?? 0;
    return `${w}\u2013${l}\u2013${ti}`;
  };

  return (
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
          Weekly Power Rankings · {year} · Week {week}
        </h2>
        <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
          Total Z-score across FG%, FT%, 3PM, REB, AST, STL, BLK, DD, PTS.
        </p>

        {loadingWeek && <div>Loading week data...</div>}

        {!loadingWeek && weekTeams.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
            No data for this week/year.
          </div>
        )}

        {!loadingWeek && weekTeams.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
              <thead>
                <tr>
                  <th style={{ ...thStyle, cursor: "default" }}>Rank</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Team</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Total Z</th>
                  {cats.map((cat) => (
                    <th key={cat} style={{ ...thStyle, cursor: "default" }}>
                      {cat}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {weekTeams.map((t) => {
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
                      <td style={{ ...tdStyle, fontWeight: 600 }}>{totalZ.toFixed(2)}</td>
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
          Season Power Rankings · {year}
        </h2>
        <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
          Averaged total Z-score across all weeks played.
        </p>

        {loadingSeason && <div>Loading season data...</div>}

        {!loadingSeason && seasonTeams.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
            No season data for this year.
          </div>
        )}

        {!loadingSeason && seasonTeams.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
              <thead>
                <tr>
                  <th style={{ ...thStyle, cursor: "default" }}>Rank</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Team</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Weeks</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Avg Total Z</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Sum Total Z</th>
                </tr>
              </thead>
              <tbody>
                {seasonTeams.map((t) => {
                  const avgZ = typeof t.avgTotalZ === "number" ? t.avgTotalZ : 0;
                  const sumZ = typeof t.sumTotalZ === "number" ? t.sumTotalZ : 0;

                  return (
                    <tr key={t.teamId}>
                      <td style={tdStyle}>{t.rank ?? "-"}</td>
                      <td style={{ ...tdStyle, fontWeight: 600 }}>{t.teamName}</td>
                      <td style={tdStyle}>{t.weeks ?? "-"}</td>
                      <td style={{ ...tdStyle, fontWeight: 600 }}>{avgZ.toFixed(2)}</td>
                      <td style={tdStyle}>{sumZ.toFixed(2)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Standings */}
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
          Standings · {standingsYear}
        </h2>
        <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
          Matchup record (W–L–T) and category record (CW–CL–CT) through the last completed week.
        </p>

        {loadingLeague && <div>Loading standings...</div>}

        {!loadingLeague && sortedStandings.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
            No standings available for this season.
          </div>
        )}

        {!loadingLeague && sortedStandings.length > 0 && (
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
              <thead>
                <tr>
                  <th style={{ ...thStyle, cursor: "default" }}>#</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Team</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Owner</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Matchup</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Categories</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Final Rank</th>
                </tr>
              </thead>
              <tbody>
                {sortedStandings.map((t, idx) => (
                  <tr key={t.teamId ?? idx}>
                    <td style={tdStyle}>{idx + 1}</td>
                    <td style={{ ...tdStyle, fontWeight: 600 }}>{t.teamName}</td>
                    <td style={tdStyle}>{t.owners ?? "-"}</td>
                    <td style={tdStyle}>{formatMatchupRecord(t)}</td>
                    <td style={tdStyle}>{formatCategoryRecord(t)}</td>
                    <td style={tdStyle}>{t.finalRank ?? t.finalStanding ?? "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            {/* Meta footer */}
            <div style={{ marginTop: 10, color: "#64748b", fontSize: "0.8rem" }}>
              {typeof currentWeek === "number" && (
                <span style={{ marginRight: 12 }}>
                  Completed through week: <b>{currentWeek}</b>
                </span>
              )}
              {typeof inProgressWeek === "number" && (
                <span style={{ marginRight: 12 }}>
                  In-progress week: <b>{inProgressWeek}</b>
                </span>
              )}
              {completedWeeks.length > 0 && (
                <span>
                  Completed weeks: {completedWeeks.join(", ")}
                </span>
              )}
            </div>
          </div>
        )}
      </section>
    </>
  );
}

export default OverviewTab;