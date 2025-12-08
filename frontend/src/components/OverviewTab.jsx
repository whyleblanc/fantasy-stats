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
                  {categories.map((cat) => (
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
                      <td style={{ ...tdStyle, fontWeight: 600 }}>
                        {totalZ.toFixed(2)}
                      </td>
                      {categories.map((cat) => {
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
                  <th style={{ ...thStyle, cursor: "default" }}>Avg Total Z</th>
                  <th style={{ ...thStyle, cursor: "default" }}>Sum Total Z</th>
                </tr>
              </thead>
              <tbody>
                {seasonTeams.map((t) => {
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

      {/* ESPN Standings – always CURRENT year (standingsYear) */}
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
          ESPN Standings · {standingsYear}
        </h2>
        <p style={{ marginTop: 0, color: "#9ca3af", fontSize: "0.85rem" }}>
          Raw standings from ESPN for season {standingsYear}. Sorted by final
          standing if available, otherwise by record and points for.
        </p>

        {loadingLeague && <div>Loading standings...</div>}

        {!loadingLeague && standingsTeams.length === 0 && (
          <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
            No standings available for this season.
          </div>
        )}

        {!loadingLeague && standingsTeams.length > 0 && (
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
                  const teams = [...standingsTeams];

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
}

export default OverviewTab;