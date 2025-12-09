// src/components/HistoryChart.jsx
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from "recharts";

function HistoryChart({ chartData, chartMode, chartCategory, comparisonTeamId }) {
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
        {chartMode === "totalZ" && "Weekly Total Z vs League Average"}
        {chartMode === "rank" && "Weekly Rank (1 = best)"}
        {chartMode === "category" &&
          `Weekly ${chartCategory} Z vs League Avg`}
      </h3>
      <div style={{ width: "100%", height: 260 }}>
        <ResponsiveContainer>
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
            <XAxis dataKey="week" />
            <YAxis />
            <Tooltip />
            <Legend />

            {chartMode === "totalZ" && (
              <>
                <Line
                  type="monotone"
                  dataKey="totalZ"
                  name="Team Total Z"
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="leagueAvgTotalZ"
                  name="League Avg Total Z"
                  dot={false}
                  strokeWidth={2}
                  strokeDasharray="4 4"
                />
                {comparisonTeamId && (
                  <Line
                    type="monotone"
                    dataKey="compTotalZ"
                    name="Comparison Total Z"
                    dot={false}
                    strokeWidth={2}
                    stroke="#ef4444"
                  />
                )}
              </>
            )}

            {chartMode === "rank" && (
              <>
                <Line
                  type="monotone"
                  dataKey="rankInverted"
                  name="Rank (1 = best)"
                  dot={true}
                  strokeWidth={2}
                />
                {comparisonTeamId && (
                  <Line
                    type="monotone"
                    dataKey="compRankInverted"
                    name="Comparison Rank (1 = best)"
                    dot={true}
                    strokeWidth={2}
                    stroke="#ef4444"
                  />
                )}
              </>
            )}

            {chartMode === "category" && (
              <>
                <Line
                  type="monotone"
                  dataKey="catZ"
                  name={`${chartCategory} Z`}
                  dot={false}
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="leagueCatZ"
                  name={`League Avg ${chartCategory} Z`}
                  dot={false}
                  strokeWidth={2}
                  strokeDasharray="4 4"
                />
                {comparisonTeamId && (
                  <Line
                    type="monotone"
                    dataKey="compCatZ"
                    name={`Comparison ${chartCategory} Z`}
                    dot={false}
                    strokeWidth={2}
                    stroke="#ef4444"
                  />
                )}
              </>
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

export default HistoryChart;