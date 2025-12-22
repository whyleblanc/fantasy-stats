// src/components/HistoryHeader.jsx
function HistoryHeader({
  teams,
  selectedTeamId,
  onChangeTeam,
  comparisonTeamId,
  onChangeComparisonTeam,
  loadingHistory,
  loadingComparison,
}) {
  const handlePrimaryChange = (e) => {
    const value = Number(e.target.value);
    if (!value) return;
    onChangeTeam?.(value);
  };

  const teamOptions = Array.isArray(teams)
    ? [...teams].sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
    : [];

  const handleComparisonChange = (e) => {
    const value = Number(e.target.value);
    if (!value) {
      onChangeComparisonTeam?.(null);
      return;
    }
    onChangeComparisonTeam?.(value);
  };

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
      {/* Primary team */}
      <div>
        <label style={{ fontSize: "0.9rem" }}>Team</label>
        <select
          value={selectedTeamId || ""}
          onChange={handlePrimaryChange}
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
          <option value="" disabled>
            Select a team…
          </option>
        {teamOptions.map((t) => (
          <option key={t.teamId} value={t.teamId} disabled={t.teamId === selectedTeamId}>
            {t.rank ? `#${t.rank} · ` : ""}{t.teamName}
          </option>
        ))}
        </select>
      </div>

      {/* Comparison team */}
      <div>
        <label style={{ fontSize: "0.9rem" }}>Compare vs</label>
        <select
          value={comparisonTeamId || ""}
          onChange={handleComparisonChange}
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
          <option value="">(None)</option>
        {teamOptions.map((t) => (
          <option key={t.teamId} value={t.teamId} disabled={t.teamId === selectedTeamId}>
            {t.rank ? `#${t.rank} · ` : ""}{t.teamName}
          </option>
        ))}
        </select>
      </div>

      {loadingHistory && (
        <span style={{ fontSize: "0.85rem", color: "#9ca3af" }}>
          Loading team history…
        </span>
      )}
      {loadingComparison && (
        <span style={{ fontSize: "0.85rem", color: "#9ca3af" }}>
          Loading comparison…
        </span>
      )}
    </section>
  );
}

export default HistoryHeader;