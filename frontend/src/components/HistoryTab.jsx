// src/components/HistoryTab.jsx
import { useEffect, useState } from "react";
import { thStyle, tdStyle, renderZCell } from "../ui/table";
import { getLeague, getTeamHistory } from "../api/client";

function HistoryTab({ year, categories }) {
  const [teams, setTeams] = useState([]);
  const [selectedTeamId, setSelectedTeamId] = useState(null);
  const [historyPayload, setHistoryPayload] = useState(null);
  const [loadingTeams, setLoadingTeams] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState(null);

  // Load team list for the selected year
  useEffect(() => {
    let cancelled = false;
    async function loadTeams() {
      setLoadingTeams(true);
      setError(null);
      try {
        const data = await getLeague(year);
        if (cancelled) return;
        const list = (data.teams || []).filter((t) => t.teamId && t.teamId !== 0);
        setTeams(list);

        // Default selection if none
        if (!selectedTeamId && list.length > 0) {
          setSelectedTeamId(list[0].teamId);
        }
      } catch (e) {
        if (!cancelled) {
          console.error(e);
          setError(e.message || "Failed to load teams");
          setTeams([]);
        }
      } finally {
        if (!cancelled) setLoadingTeams(false);
      }
    }

    loadTeams();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year]);

  // Load history when team changes
  useEffect(() => {
    if (!selectedTeamId) return;
    let cancelled = false;

    async function loadHistory() {
      setLoadingHistory(true);
      setError(null);
      try {
        const data = await getTeamHistory(year, selectedTeamId);
        if (cancelled) return;
        setHistoryPayload(data);
      } catch (e) {
        if (!cancelled) {
          console.error(e);
          setError(e.message || "Failed to load team history");
          setHistoryPayload(null);
        }
      } finally {
        if (!cancelled) setLoadingHistory(false);
      }
    }

    loadHistory();
    return () => {
      cancelled = true;
    };
  }, [year, selectedTeamId]);

  const history = historyPayload?.history || [];
  const teamName = historyPayload?.teamName || "";

  return (
    <section
      style={{
        marginBottom: "24px",
        padding: "16px",
        borderRadius: "12px",
        background: "rgba(15,23,42,0.9)",
        boxShadow: "0 20px 35px rgba(15,23,42,0.7)",
      }}
    >
      <h2 style={{ marginTop: 0, fontSize: "1.1rem" }}>
        Team History · {year}
      </h2>

      <div
        style={{
          marginBottom: "16px",
          display: "flex",
          flexWrap: "wrap",
          gap: "12px",
          alignItems: "center",
        }}
      >
        <div>
          <label style={{ fontSize: "0.9rem" }}>Team</label>
          <select
            value={selectedTeamId || ""}
            onChange={(e) => setSelectedTeamId(Number(e.target.value))}
            disabled={loadingTeams || teams.length === 0}
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
            {teams.length === 0 && (
              <option value="">No teams</option>
            )}
            {teams.map((t) => (
              <option key={t.teamId} value={t.teamId}>
                {t.teamName}
              </option>
            ))}
          </select>
        </div>

        {teamName && (
          <div style={{ fontSize: "0.9rem", color: "#9ca3af" }}>
            Selected: <strong>{teamName}</strong>
          </div>
        )}

        {error && (
          <span style={{ color: "#fca5a5", fontSize: "0.85rem" }}>
            {error}
          </span>
        )}
      </div>

      {loadingHistory && <div>Loading team history…</div>}

      {!loadingHistory && history.length === 0 && (
        <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
          No history data for this team/year.
        </div>
      )}

      {!loadingHistory && history.length > 0 && (
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
                <th style={thStyle}>Weekly Rank</th>
                <th style={thStyle}>Total Z</th>
                <th style={thStyle}>Cumulative Z</th>
                {categories.map((cat) => (
                  <th key={cat} style={thStyle}>
                    {cat} Z
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {history.map((row) => {
                const z = row.zscores || {};
                const totalZ =
                  typeof row.totalZ === "number" ? row.totalZ : 0;
                const cumZ =
                  typeof row.cumulativeTotalZ === "number"
                    ? row.cumulativeTotalZ
                    : 0;

                return (
                  <tr key={row.week}>
                    <td style={tdStyle}>{row.week}</td>
                    <td style={tdStyle}>{row.rank ?? "-"}</td>
                    <td style={{ ...tdStyle, fontWeight: 600 }}>
                      {totalZ.toFixed(2)}
                    </td>
                    <td style={tdStyle}>{cumZ.toFixed(2)}</td>
                    {categories.map((cat) => {
                      const keyName = `${cat}_z`;
                      return renderZCell(z[keyName] ?? 0, keyName);
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export default HistoryTab;