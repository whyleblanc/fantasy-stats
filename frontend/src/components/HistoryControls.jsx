// src/components/HistoryControls.jsx
function HistoryControls({
  chartMode,
  onChangeChartMode,
  chartCategory,
  onChangeChartCategory,
  categories,
  maxWeekForSlider,
  weekLimit,
  onChangeWeekLimit,
}) {
  const cats = Array.isArray(categories) ? categories : []; // ✅ add this

  const handleSlider = (e) => {
    const value = Number(e.target.value);
    onChangeWeekLimit(value || null);
  };

  return (
    <section style={{ marginBottom: "8px", display: "flex", flexWrap: "wrap", gap: "12px", alignItems: "center" }}>
      <div>
        <label style={{ fontSize: "0.85rem", display: "block", marginBottom: 4 }}>
          Chart Metric
        </label>
        <select
          value={chartMode}
          onChange={(e) => onChangeChartMode(e.target.value)}
          style={{
            padding: "4px 8px",
            background: "#020617",
            border: "1px solid #334155",
            color: "#e5e7eb",
            borderRadius: "6px",
            minWidth: "160px",
          }}
        >
          <option value="totalZ">Weekly Total Z</option>
          <option value="rank">Weekly Rank (1 = best)</option>
          <option value="category">Category Z</option>
        </select>
      </div>

      {chartMode === "category" && (
        <div>
          <label style={{ fontSize: "0.85rem", display: "block", marginBottom: 4 }}>
            Category
          </label>
          <select
            value={chartCategory}
            onChange={(e) => onChangeChartCategory(e.target.value)}
            style={{
              padding: "4px 8px",
              background: "#020617",
              border: "1px solid #334155",
              color: "#e5e7eb",
              borderRadius: "6px",
              minWidth: "130px",
            }}
          >
            {cats.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      )}

      {maxWeekForSlider > 0 && (
        <div style={{ minWidth: "220px" }}>
          <label style={{ fontSize: "0.85rem", display: "block", marginBottom: 4 }}>
            Week range (1 → {weekLimit || maxWeekForSlider})
          </label>
          <input
            type="range"
            min={1}
            max={maxWeekForSlider}
            value={weekLimit || maxWeekForSlider}
            onChange={handleSlider}
            style={{ width: "100%" }}
          />
        </div>
      )}
    </section>
  );
}

export default HistoryControls;