// Vote server for bonitabluehair.com ("Does he make it?").
//   GET  /votes  -> { votes: [{ id, name, pick, level, t, switched }] }, earliest call first
//   POST /vote   { token, pick: "yes" | "no", name } -> { votes, you }
// Each browser keeps a random secret token. Votes are stored under a hash of it, so the public list
// can't be used to change someone else's vote. The level stamp comes from the site's own data, not
// from the browser, and voting closes once he hits 60 or Christmas arrives.

const ORIGINS = [
  "https://bonitabluehair.com",
  "https://www.bonitabluehair.com",
  "http://localhost:8765",
  "http://127.0.0.1:8765",
];
const HISTORY_URL = "https://bonitabluehair.com/data/history.json";
const LIVE_URL = "https://raw.githubusercontent.com/TwinkieSlamer/bonitabluehair-live/main/live.json";
const DAY = 864e5;
const NEW_VOTES_PER_NETWORK_PER_DAY = 20;
const MAX_VOTES = 2000;

function corsHeaders(req) {
  const origin = req.headers.get("Origin");
  const h = { Vary: "Origin" };
  if (origin && ORIGINS.includes(origin)) {
    h["Access-Control-Allow-Origin"] = origin;
    h["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS";
    h["Access-Control-Allow-Headers"] = "Content-Type";
    h["Access-Control-Max-Age"] = "86400";
  }
  return h;
}

function json(req, status, body) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...corsHeaders(req) },
  });
}

async function sha256(s) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function fetchJson(url) {
  try {
    const r = await fetch(url, { cf: { cacheTtl: 120, cacheEverything: true } });
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

// His current level and whether the bet is settled, read the same way the race page reads it:
// the latest Armory logout, or his addon's report when it's newer and higher.
async function raceState() {
  const [history, live] = await Promise.all([fetchJson(HISTORY_URL), fetchJson(LIVE_URL)]);
  if (!history) return null;
  const snaps = (history.snapshots || []).slice().sort((a, b) => a.t - b.t);
  const last = snaps[snaps.length - 1];
  let level = last ? last.level : 1;
  if (live && typeof live.level === "number" && live.time && (!last || live.time * 1000 > last.t) && live.level > level) {
    level = live.level;
  }
  level = Math.max(1, Math.min(60, Math.floor(level)));
  const deadline = Date.parse(history.deadline);
  return { level, closed: level >= 60 || Date.now() >= deadline };
}

function cleanName(raw) {
  return String(raw == null ? "" : raw)
    .replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁠-⁩﻿]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 24);
}

async function listVotes(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, name, pick, level, t, switched FROM votes ORDER BY t ASC LIMIT ?"
  ).bind(MAX_VOTES).all();
  return results;
}

async function castVote(req, env) {
  let body;
  try {
    body = await req.json();
  } catch {
    return json(req, 400, { error: "bad_request" });
  }
  const token = typeof body.token === "string" ? body.token : "";
  const pick = body.pick;
  if (!/^[0-9a-f]{64}$/.test(token) || (pick !== "yes" && pick !== "no")) return json(req, 400, { error: "bad_request" });
  const name = cleanName(body.name);

  const race = await raceState();
  if (!race) return json(req, 503, { error: "unavailable" });
  if (race.closed) return json(req, 409, { error: "closed" });

  const id = (await sha256(token)).slice(0, 16);
  const now = Date.now();
  const prev = await env.DB.prepare("SELECT pick, name FROM votes WHERE id = ?").bind(id).first();

  if (!prev) {
    const network = await sha256("bbh-votes|" + (req.headers.get("CF-Connecting-IP") || "unknown"));
    const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM votes WHERE ip = ? AND created > ?").bind(network, now - DAY).first();
    if (recent && recent.n >= NEW_VOTES_PER_NETWORK_PER_DAY) return json(req, 429, { error: "too_many" });
    const total = await env.DB.prepare("SELECT COUNT(*) AS n FROM votes").first();
    if (total && total.n >= MAX_VOTES) return json(req, 429, { error: "full" });
    await env.DB.prepare(
      "INSERT INTO votes (id, name, pick, level, t, switched, created, ip) VALUES (?, ?, ?, ?, ?, 0, ?, ?)"
    ).bind(id, name, pick, race.level, now, now, network).run();
  } else if (prev.pick !== pick) {
    // Switching sides keeps the original call's level and records the level at the switch.
    await env.DB.prepare("UPDATE votes SET pick = ?, name = ?, switched = ?, t = ? WHERE id = ?")
      .bind(pick, name, race.level, now, id).run();
  } else if (prev.name !== name) {
    await env.DB.prepare("UPDATE votes SET name = ? WHERE id = ?").bind(name, id).run();
  }

  return json(req, 200, { votes: await listVotes(env), you: id });
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: corsHeaders(req) });
    try {
      if (url.pathname === "/votes" && req.method === "GET") return json(req, 200, { votes: await listVotes(env) });
      if (url.pathname === "/vote" && req.method === "POST") return await castVote(req, env);
      return json(req, 404, { error: "not_found" });
    } catch (e) {
      console.error(e);
      return json(req, 500, { error: "server_error" });
    }
  },
};
