// src/components/HistoryTab.jsx
import { useEffect, useMemo, useState } from "react";
import { getTeamHistory } from "../api/client";

import HistoryHeader from "./HistoryHeader";
import HistorySummary from "./HistorySummary";
import HistoryControls from "./HistoryControls";
import HistoryChart from "./HistoryChart";
import HistoryTable from "./HistoryTable";

function HistoryTab({
  year,
  seasonPower,
  historyData,
  loadingHistory,
  selectedTeamId,
  onChangeTeam,
  categories,
}) {
  const teams = seasonPower?.teams || [];
  const history = historyData?.history || [];
  const teamName = historyData?.teamName || "";

  // comparison state
  const [comparisonTeamId, setComparisonTeamId] = useState(null);
  const [comparisonHistoryData, setComparisonHistoryData] = useState(null);
  const [loadingComparison, setLoadingComparison] = useState(false);

  // chart state
  const [chartMode, setChartMode] = useState("totalZ"); // 'totalZ' | 'rank' | 'category'
  const [chartCategory, setChartCategory] = useState(
    categories[0] || "FG%"
  );
  const [weekLimit, setWeekLimit] = useState(null);

  // reset week limit when history changes
  useEffect(() => {
    if (!history.length) {
      setWeekLimit(null);
      return;
    }
    const maxWeek = Math.max(...history.map((h) => h.week || 0));
    setWeekLimit(maxWeek);
  }, [history, year]);

  // comparison fetch
  const fetchComparisonHistory = async (teamId) => {
    if (!teamId) {
      setComparisonHistoryData(null);
      return;
    }
    setLoadingComparison(true);
    try {
      const data = await getTeamHistory(year, teamId);
      setComparisonHistoryData(data);
    } catch (e) {
      console.error("Comparison history error:", e);
      setComparisonHistoryData(null);
    } finally {
      setLoadingComparison(false);
    }
  };

  const handleComparisonTeam = (teamId) => {
    if (!teamId) {
      setComparisonTeamId(null);
      setComparisonHistoryData(null);
      return;
    }
    setComparisonTeamId(teamId);
    fetchComparisonHistory(teamId);
  };

  // filtered by week limit
  const primaryFiltered = useMemo(() => {
    if (!history.length) return [];
    if (!weekLimit) return history;
    return history.filter((h) => (h.week || 0) <= weekLimit);
  }, [history, weekLimit]);

  const comparisonFiltered = useMemo(() => {
    const compHist = comparisonHistoryData?.history || [];
    if (!compHist.length) return [];
    if (!weekLimit) return compHist;
    return compHist.filter((h) => (h.week || 0) <= weekLimit);
  }, [comparisonHistoryData, weekLimit]);

  // chart data
  const chartData = useMemo(() => {
    if (!primaryFiltered.length) return [];

    const compMap = new Map(
      comparisonFiltered.map((h) => [h.week, h])
    );

    return primaryFiltered.map((h) => {
      const week = h.week;
      const comp = compMap.get(week);

      const totalZ =
        typeof h.totalZ === "number" ? Number(h.totalZ.toFixed(3)) : 0;
      const leagueAvgTotalZ =
        typeof h.leagueAverageTotalZ === "number"
          ? Number(h.leagueAverageTotalZ.toFixed(3))
          : 0;

      const rank = typeof h.rank === "number" ? h.rank : null;
      const rankInverted = typeof rank === "number" ? -rank : null;

      const zscores = h.zscores || {};
      const leagueZscores = h.leagueAverageZscores || {};

      const catKey = `${chartCategory}_z`;
      const catZ =
        typeof zscores[catKey] === "number"
          ? Number(zscores[catKey].toFixed(3))
          : 0;
      const leagueCatZ =
        typeof leagueZscores[catKey] === "number"
          ? Number(leagueZscores[catKey].toFixed(3))
          : 0;

      let compTotalZ = null;
      let compRankInverted = null;
      let compCatZ = null;

      if (comp) {
        const cTotal =
          typeof comp.totalZ === "number"
            ? Number(comp.totalZ.toFixed(3))
            : 0;
        const cRank =
          typeof comp.rank === "number" ? comp.rank : null;
        const cRankInv =
          typeof cRank === "number" ? -cRank : null;
        const cZscores = comp.zscores || {};
        const cCatZ =
          typeof cZscores[catKey] === "number"
            ? Number(cZscores[catKey].toFixed(3))
            : 0;

        compTotalZ = cTotal;
        compRankInverted = cRankInv;
        compCatZ = cCatZ;
      }

      return {
        week,
        totalZ,
        leagueAvgTotalZ,
        compTotalZ,
        rankInverted,
        compRankInverted,
        catZ,
        leagueCatZ,
        compCatZ,
      };
    });
  }, [primaryFiltered, comparisonFiltered, chartCategory]);

  // summary stats
  const summary = useMemo(() => {
    if (!history.length) {
      return {
        bestWeek: null,
        worstWeek: null,
        avgRank: null,
        finalRank: null,
      };
    }

    let best = history[0];
    let worst = history[0];
    let rankSum = 0;
    let rankCount = 0;

    history.forEach((h) => {
      const tz = typeof h.totalZ === "number" ? h.totalZ : 0;
      const br = typeof best.totalZ === "number" ? best.totalZ : 0;
      const wr = typeof worst.totalZ === "number" ? worst.totalZ : 0;

      if (tz > br) best = h;
      if (tz < wr) worst = h;

      if (typeof h.rank === "number" && h.rank > 0) {
        rankSum += h.rank;
        rankCount += 1;
      }
    });

    const avgRank = rankCount ? rankSum / rankCount : null;
    const finalRankEntry = history[history.length - 1];

    return {
      bestWeek: best,
      worstWeek: worst,
      avgRank,
      finalRank: finalRankEntry?.rank ?? null,
    };
  }, [history]);

  const maxWeekForSlider = useMemo(() => {
    if (!history.length) return 0;
    return Math.max(...history.map((h) => h.week || 0));
  }, [history]);

  // ---- render ----
  return (
    <div>
      <HistoryHeader
        teams={teams}
        selectedTeamId={selectedTeamId}
        onChangeTeam={onChangeTeam}
        comparisonTeamId={comparisonTeamId}
        onChangeComparisonTeam={handleComparisonTeam}
        loadingHistory={loadingHistory}
        loadingComparison={loadingComparison}
      />

      {!selectedTeamId && !loadingHistory && (
        <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
          Select a team to see their week-by-week history.
        </div>
      )}

      {selectedTeamId && !loadingHistory && !history.length && (
        <div style={{ color: "#9ca3af", fontSize: "0.9rem" }}>
          No history data for this team/year.
        </div>
      )}

      {selectedTeamId && history.length > 0 && (
        <>
          <h2 style={{ marginTop: 0, marginBottom: 8, fontSize: "1.1rem" }}>
            Team History · {teamName} · {year}
          </h2>

          <HistorySummary summary={summary} totalWeeks={history.length} />

          <HistoryControls
            chartMode={chartMode}
            onChangeChartMode={setChartMode}
            chartCategory={chartCategory}
            onChangeChartCategory={setChartCategory}
            categories={categories}
            maxWeekForSlider={maxWeekForSlider}
            weekLimit={weekLimit}
            onChangeWeekLimit={setWeekLimit}
          />

          <HistoryChart
            chartData={chartData}
            chartMode={chartMode}
            chartCategory={chartCategory}
            comparisonTeamId={comparisonTeamId}
          />

          <HistoryTable history={history} categories={categories} />
        </>
      )}
    </div>
  );
}

export default HistoryTab;