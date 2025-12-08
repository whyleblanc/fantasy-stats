// frontend/src/api/client.js

const API_BASE = "http://127.0.0.1:5001";

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

function getLeague(year) {
  return fetchJson("/api/league", { year });
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
};