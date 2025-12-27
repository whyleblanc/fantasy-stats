// frontend/src/api/client.js

// Prefer env value, fall back to same-origin ("" = relative URLs like /api/meta)
const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

// ------------------------
// URL + fetch helpers
// ------------------------
function buildUrl(path, params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") return;
    search.set(key, String(value).trim());
  });
  const qs = search.toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function fetchJson(path, params = {}) {
  const url = buildUrl(path, params);
  const res = await fetch(url);

  if (!res.ok) {
    const text = await res.text();
    throw new Error(
      `Request failed: ${res.status} ${res.statusText} – ${text || url}`
    );
  }

  return res.json();
}

// ------------------------
// High-level API endpoints
// ------------------------

function getMeta(year) {
  return fetchJson("/api/meta", year != null ? { year } : {});
}

function getLeague(year, refresh = false) {
  return fetchJson("/api/league", { year, refresh: refresh ? 1 : 0 });
}

function getWeekPower(year, week, refresh = false) {
  return fetchJson("/api/analysis/week-power", {
    year,
    week,
    refresh: refresh ? 1 : 0,
  });
}

function getSeasonPower(year, refresh = false) {
  return fetchJson("/api/analysis/season-power", {
    year,
    refresh: refresh ? 1 : 0,
  });
}

function getWeekZscores(year, week, refresh = false) {
  return fetchJson("/api/analysis/week-zscores", {
    year,
    week,
    refresh: refresh ? 1 : 0,
  });
}

function getSeasonZscores(year, refresh = false) {
  return fetchJson("/api/analysis/season-zscores", {
    year,
    refresh: refresh ? 1 : 0,
  });
}

function getTeamHistory(year, teamId, refresh = false) {
  return fetchJson("/api/analysis/team-history", {
    year,
    teamId,
    refresh: refresh ? 1 : 0,
  });
}

// ------------------------
// Opponent endpoints
// ------------------------

/**
 * getOpponentMatrix
 *
 * Overloaded:
 *  - Legacy single-year:
 *      getOpponentMatrix(year, teamId, refresh?)
 *  - Multi-year range:
 *      getOpponentMatrix({
 *        startYear,
 *        endYear,
 *        teamId,
 *        currentOwnerEraOnly?: boolean,
 *        refresh?: boolean
 *      })
 */
function getOpponentMatrix(arg1, teamId, refresh = false) {
  let params;

  if (typeof arg1 === "object" && arg1 !== null) {
    // New object-style call
    params = { ...arg1 };
  } else {
    // Legacy positional call
    params = {
      year: arg1,
      teamId,
      refresh: refresh ? 1 : 0,
    };
  }

  if ("currentOwnerEraOnly" in params) {
    params.currentOwnerEraOnly = params.currentOwnerEraOnly ? 1 : 0;
  }

  if ("refresh" in params && typeof params.refresh === "boolean") {
    params.refresh = params.refresh ? 1 : 0;
  }

  return fetchJson("/api/analysis/opponent-matrix", params);
}

// (Still available if you ever want the single-team cat heatmap)
function getOpponentHeatmap(year, teamId, refresh = false) {
  return fetchJson("/api/analysis/opponent-heatmap", {
    year,
    teamId,
    refresh: refresh ? 1 : 0,
  });
}

// Thin convenience wrapper for range mode, if you want it elsewhere
function getOpponentMatrixMulti(
  startYear,
  endYear,
  teamId,
  currentOwnerEraOnly = false,
  refresh = false
) {
  return getOpponentMatrix({
    startYear,
    endYear,
    teamId,
    currentOwnerEraOnly,
    refresh,
  });
}

function getAnalysisHealth(year) {
  return fetchJson("/api/analysis/health", { year });
}

function getAwards({
  scope = "league",
  mode = "summary",
  year = "all_time",
  teamId = null,
  ownerCode = null,
  currentOwnerEraOnly = true,
} = {}) {
  return fetchJson("/api/analysis/awards", {
    scope,
    mode,
    year,
    teamId,
    ownerCode,
    currentOwnerEraOnly: currentOwnerEraOnly ? 1 : 0,
  });
}

// ------------------------
// Unified API object
// ------------------------
export const api = {
  getMeta,
  getLeague,
  getWeekPower,
  getSeasonPower,
  getWeekZscores,
  getSeasonZscores,
  getTeamHistory,
  getOpponentMatrix,
  getOpponentHeatmap,
  getOpponentMatrixMulti,
  getAnalysisHealth,
  getAwards,
};

// Also export individual functions if needed
export {
  getMeta,
  getLeague,
  getWeekPower,
  getSeasonPower,
  getWeekZscores,
  getSeasonZscores,
  getTeamHistory,
  getOpponentMatrix,
  getOpponentHeatmap,
  getOpponentMatrixMulti,
  getAnalysisHealth,
  getAwards,
};

