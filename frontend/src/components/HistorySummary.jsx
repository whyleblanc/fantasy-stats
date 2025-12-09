// src/components/HistorySummary.jsx
function HistorySummary({ summary, totalWeeks }) {
  return (
    <section
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: "12px",
        marginBottom: "16px",
      }}
    >
      <SummaryCard
        label="Best Week (Total Z)"
        value={
          summary.bestWeek ? summary.bestWeek.totalZ?.toFixed(2) : "—"
        }
        footer={
          summary.bestWeek
            ? `Week ${summary.bestWeek.week}, Rank ${
                summary.bestWeek.rank ?? "-"
              }`
            : ""
        }
      />
      <SummaryCard
        label="Worst Week (Total Z)"
        value={
          summary.worstWeek ? summary.worstWeek.totalZ?.toFixed(2) : "—"
        }
        footer={
          summary.worstWeek
            ? `Week ${summary.worstWeek.week}, Rank ${
                summary.worstWeek.rank ?? "-"
              }`
            : ""
        }
      />
      <SummaryCard
        label="Avg Weekly Rank"
        value={summary.avgRank ? summary.avgRank.toFixed(1) : "—"}
        footer={
          summary.finalRank
            ? `Last week rank: ${summary.finalRank}`
            : ""
        }
      />
      <SummaryCard label="Total Weeks" value={totalWeeks} footer="" />
    </section>
  );
}

function SummaryCard({ label, value, footer }) {
  return (
    <div
      style={{
        flex: "1 1 160px",
        padding: "10px 12px",
        borderRadius: "10px",
        border: "1px solid #1e293b",
        background: "rgba(15,23,42,0.9)",
      }}
    >
      <div style={{ fontSize: "0.8rem", color: "#9ca3af" }}>{label}</div>
      <div
        style={{
          marginTop: 4,
          fontSize: "1.1rem",
          fontWeight: 600,
          color: "#e5e7eb",
        }}
      >
        {value}
      </div>
      {footer && (
        <div
          style={{
            marginTop: 4,
            fontSize: "0.75rem",
            color: "#64748b",
          }}
        >
          {footer}
        </div>
      )}
    </div>
  );
}

export default HistorySummary;