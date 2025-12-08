// src/components/HistoryTab.jsx
export default function HistoryTab({
  year,
  teams,
  selectedTeamId,
  setSelectedTeamId,
  teamHistory,
  loadingHistory,
}) {
  const handleChange = (e) => {
    const v = Number(e.target.value);
    setSelectedTeamId(Number.isNaN(v) ? null : v);
  };

  return (
    <section style={{ marginTop: 16 }}>
      <h2 style={{ marginBottom: 8 }}>Team History · {year}</h2>

      <div style={{ marginBottom: 12 }}>
        <label style={{ fontSize: "0.9rem", marginRight: 8 }}>Team</label>
        <select
          value={selectedTeamId || ""}
          onChange={handleChange}
          style={{
            padding: "4px 8px",
            borderRadius: 6,
            border: "1px solid #334155",
            background: "#020617",
            color: "#e5e7eb",
            minWidth: 160,
          }}
        >
          <option value="">Select a team…</option>
          {teams.map((t) => (
            <option key={t.teamId} value={t.teamId}>
              {t.teamName}
            </option>
          ))}
        </select>
      </div>

      {loadingHistory && <div>Loading team history…</div>}

      {!loadingHistory && selectedTeamId && !teamHistory && (
        <div style={{ fontSize: "0.9rem", color: "#94a3b8" }}>
          No history data yet for this team.
        </div>
      )}

      {!loadingHistory && teamHistory && (
        <pre
          style={{
            marginTop: 12,
            padding: 12,
            borderRadius: 8,
            background: "#020617",
            border: "1px solid #1f2937",
            maxHeight: 320,
            overflow: "auto",
            fontSize: "0.8rem",
          }}
        >
          {JSON.stringify(teamHistory, null, 2)}
        </pre>
      )}
    </section>
  );
}