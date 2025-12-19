// src/components/HistoryTable.jsx
import { thStyle, tdStyle, renderZCell } from "../ui/table";

function HistoryTable({ history, categories }) {
  const cats = Array.isArray(categories) ? categories : [];
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
      <h3
        style={{
          marginTop: 0,
          marginBottom: 8,
          fontSize: "1rem",
        }}
      >
        Week-by-Week Breakdown
      </h3>
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
              <th style={thStyle}>Rank</th>
              <th style={thStyle}>Total Z</th>
              <th style={thStyle}>Cumulative Z</th>
              {cats.map((cat) => (
                <th key={cat} style={thStyle}>
                  {cat} Z
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {history.map((h) => {
              const zscores = h.zscores || {};
              const totalZ =
                typeof h.totalZ === "number" ? h.totalZ : 0;
              const cumZ =
                typeof h.cumulativeTotalZ === "number"
                  ? h.cumulativeTotalZ
                  : 0;

              return (
                <tr key={h.week}>
                  <td style={tdStyle}>{h.week}</td>
                  <td style={tdStyle}>{h.rank ?? "-"}</td>
                  <td style={{ ...tdStyle, fontWeight: 600 }}>
                    {totalZ.toFixed(2)}
                  </td>
                  <td style={tdStyle}>{cumZ.toFixed(2)}</td>
                  {cats.map((cat) => {
                    const keyName = `${cat}_z`;
                    return renderZCell(
                      zscores[keyName] ?? 0,
                      keyName
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default HistoryTable;