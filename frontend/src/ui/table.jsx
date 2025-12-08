// src/ui/table.js

export const thStyle = {
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "1px solid #1e293b",
  position: "sticky",
  top: 0,
  background: "#020617",
  cursor: "pointer",
  whiteSpace: "nowrap",
};

export const tdStyle = {
  padding: "6px 8px",
  borderBottom: "1px solid #1e293b",
};

// Heatmap-ish cell for z-scores
export function renderZCell(z, key) {
  const value = Number.isFinite(z) ? z : 0;
  let bg = "transparent";
  let color = "#e5e7eb";

  if (value >= 1.0) {
    bg = "rgba(34,197,94,0.25)";
    color = "#bbf7d0";
  } else if (value >= 0.3) {
    bg = "rgba(34,197,94,0.15)";
  } else if (value <= -1.0) {
    bg = "rgba(248,113,113,0.25)";
    color = "#fecaca";
  } else if (value <= -0.3) {
    bg = "rgba(248,113,113,0.15)";
  }

  return (
    <td key={key} style={{ ...tdStyle, background: bg, color }}>
      {value.toFixed(2)}
    </td>
  );
}