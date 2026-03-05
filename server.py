#!/usr/bin/env python3
"""
ScoutAI — Football Analytics Bot
Data: api-football.com v3 (free: 100 req/day)
AI:   Groq API (free tier)
Host: Railway.app (free)

LOCAL:
  pip install -r requirements.txt
  python server.py  →  open http://localhost:5000

DEPLOY:
  Push to GitHub → connect Railway.app → done.
"""

import json
import os
import re
import requests
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder=".")
CORS(app)

# ── CONFIG ────────────────────────────────────────────────────────────────────
AF_BASE    = "https://v3.football.api-sports.io"
GROQ_BASE  = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.1-8b-instant"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# api-football league IDs
LEAGUE_IDS = {
    "PL":  39,   # Premier League
    "PD":  140,  # La Liga
    "BL1": 78,   # Bundesliga
    "SA":  135,  # Serie A
    "FL1": 61,   # Ligue 1
    "CL":  2,    # Champions League
    "WC":  1,    # World Cup
    "EC":  4,    # Euro Championship
}

# Auto-detect season: football seasons run Aug-May
# e.g. 2024/25 season = 2024, 2025/26 season = 2025
_now = datetime.now(timezone.utc)
CURRENT_SEASON = _now.year if _now.month >= 7 else _now.year - 1


# ── API-FOOTBALL HELPER ───────────────────────────────────────────────────────

def af_get(path, api_key, params=None):
    """Call api-football.com v3."""
    headers = {
        "x-apisports-key": api_key,
        "Accept": "application/json",
    }
    url = f"{AF_BASE}/{path.lstrip('/')}"
    r = requests.get(url, headers=headers, params=params or {}, timeout=12)
    if not r.ok:
        raise Exception(f"API-Football HTTP {r.status_code}: {r.text[:200]}")
    data = r.json()
    # API-Football returns errors inside the response body
    errors = data.get("errors", {})
    if errors:
        msg = list(errors.values())[0] if isinstance(errors, dict) else str(errors)
        raise Exception(f"API-Football error: {msg}")
    return data


def find_team(teams, query):
    """Fuzzy match team name."""
    q = query.lower().strip()
    for t in teams:
        name = t.get("team", {}).get("name", "")
        short = t.get("team", {}).get("code", "")
        for f in [name, short]:
            if f.lower() == q:
                return t
    for t in teams:
        name = t.get("team", {}).get("name", "")
        if q in name.lower() or name.lower() in q:
            return t
    q0 = q.split()[0]
    for t in teams:
        name = t.get("team", {}).get("name", "")
        if any(w.startswith(q0) for w in name.lower().split()):
            return t
    return None


def get_form_from_fixtures(fixtures, team_id):
    """Build W-D-L form string from recent fixtures."""
    results = []
    for f in reversed(fixtures):
        teams = f.get("teams", {})
        home_id = teams.get("home", {}).get("id")
        away_id = teams.get("away", {}).get("id")
        goals   = f.get("goals", {})
        hg, ag  = goals.get("home"), goals.get("away")
        if hg is None or ag is None:
            continue
        if home_id == team_id:
            results.append("W" if hg > ag else "L" if hg < ag else "D")
        elif away_id == team_id:
            results.append("W" if ag > hg else "L" if ag < hg else "D")
    return "-".join(results) if results else "N/A"


def fmt_recent(fixtures, team_id, n=5):
    """Format last N results as readable text for AI prompt."""
    lines = []
    for f in reversed(fixtures[:n]):
        teams = f.get("teams", {})
        home  = teams.get("home", {})
        away  = teams.get("away", {})
        goals = f.get("goals", {})
        hg, ag = goals.get("home", "?"), goals.get("away", "?")
        is_home = home.get("id") == team_id
        opp  = away.get("name", "?") if is_home else home.get("name", "?")
        gs   = hg if is_home else ag
        gc   = ag if is_home else hg
        try:
            res = "WIN" if int(gs) > int(gc) else "LOSS" if int(gs) < int(gc) else "DRAW"
        except Exception:
            res = "?"
        date = f.get("fixture", {}).get("date", "")[:10]
        lines.append(f"  {res} {gs}-{gc} vs {opp} ({date})")
    return "\n".join(lines) if lines else "  No data"


# ── GROQ AI ───────────────────────────────────────────────────────────────────

def groq_chat(messages, groq_key, temperature=0.3, max_tokens=1400, as_json=True):
    key = groq_key or GROQ_API_KEY
    if not key:
        raise Exception("No Groq API key. Get a free key at console.groq.com")
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if as_json:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(f"{GROQ_BASE}/chat/completions", headers=headers,
                      json=payload, timeout=30)
    if not r.ok:
        try:
            err = r.json().get("error", {}).get("message", r.text[:300])
        except Exception:
            err = r.text[:300]
        raise Exception(f"Groq API {r.status_code}: {err}")
    return r.json()["choices"][0]["message"]["content"]


def extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON object found")
    depth = end = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":   depth += 1
        elif ch == "}": depth -= 1
        if depth == 0:  end = i; break
    if not end:
        raise ValueError("Unclosed JSON")
    return json.loads(text[start:end + 1])


# ── AI PREDICTION ─────────────────────────────────────────────────────────────

def ai_predict(data, groq_key):
    home_name = data["homeTeam"]["name"]
    away_name = data["awayTeam"]["name"]
    hs  = data.get("homeStanding") or {}
    as_ = data.get("awayStanding") or {}

    # H2H lines
    h2h_lines = []
    for f in data.get("h2h", [])[:6]:
        teams  = f.get("teams", {})
        goals  = f.get("goals", {})
        date   = f.get("fixture", {}).get("date", "")[:10]
        h2h_lines.append(
            f"  {teams.get('home',{}).get('name','?')} "
            f"{goals.get('home','?')}-{goals.get('away','?')} "
            f"{teams.get('away',{}).get('name','?')} ({date})"
        )
    h2h_txt = "\n".join(h2h_lines) or "  No H2H data"

    home_recent = fmt_recent(data.get("homeFixtures", []), data["homeTeam"]["id"])
    away_recent = fmt_recent(data.get("awayFixtures", []), data["awayTeam"]["id"])

    system_msg = (
        "You are a professional football analyst with 20 years of experience. "
        "You make single definitive predictions — never hedge or list multiple options. "
        "Pick exactly ONE winner based on the data. "
        "Return ONLY a valid JSON object, no other text."
    )

    prompt = f"""Analyze this match and return your single definitive prediction as JSON.

=== MATCH ===
{home_name} (HOME) vs {away_name} (AWAY)
Competition: {data["league"]["name"]}

{home_name}:
  Position: #{hs.get("rank","?")} | P{hs.get("all",{}).get("played","?")} W{hs.get("all",{}).get("win","?")} D{hs.get("all",{}).get("draw","?")} L{hs.get("all",{}).get("lose","?")}
  Goals: scored {hs.get("all",{}).get("goals",{}).get("for","?")} conceded {hs.get("all",{}).get("goals",{}).get("against","?")}
  Points: {hs.get("points","?")} | Form: {hs.get("form","N/A")}
  Last 5:
{home_recent}

{away_name}:
  Position: #{as_.get("rank","?")} | P{as_.get("all",{}).get("played","?")} W{as_.get("all",{}).get("win","?")} D{as_.get("all",{}).get("draw","?")} L{as_.get("all",{}).get("lose","?")}
  Goals: scored {as_.get("all",{}).get("goals",{}).get("for","?")} conceded {as_.get("all",{}).get("goals",{}).get("against","?")}
  Points: {as_.get("points","?")} | Form: {as_.get("form","N/A")}
  Last 5:
{away_recent}

H2H (last meetings):
{h2h_txt}

Return EXACTLY this JSON:
{{
  "winner": "PICK ONE: {home_name} OR {away_name} OR Draw",
  "score": "e.g. 2-1",
  "confidence": "High or Medium or Low",
  "btts": "Yes or No",
  "over25": "Yes or No",
  "winProbHome": <integer 0-100>,
  "winProbDraw": <integer 0-100>,
  "winProbAway": <integer 0-100>,
  "keyFactor": "The single most decisive reason for your prediction",
  "analysis": "200 words: why this team wins, form analysis, H2H patterns, tactical edge. Be direct and confident.",
  "homeStrengths": ["strength based on data", "strength", "strength"],
  "awayStrengths": ["strength based on data", "strength", "strength"],
  "riskFactor": "The one thing that could make this prediction wrong"
}}
RULES:
- winner = exactly "{home_name}" OR "{away_name}" OR "Draw" — nothing else, no slash, no OR
- winProbHome + winProbDraw + winProbAway must equal exactly 100"""

    raw = groq_chat(
        [{"role": "system", "content": system_msg},
         {"role": "user",   "content": prompt}],
        groq_key
    )
    print(f"[Groq raw]: {raw[:300]}")
    result = extract_json(raw)

    # Safety: validate winner
    valid = [home_name, away_name, "Draw"]
    if result.get("winner") not in valid:
        ph = result.get("winProbHome", 0)
        pa = result.get("winProbAway", 0)
        pd = result.get("winProbDraw", 0)
        result["winner"] = home_name if ph >= pa and ph >= pd else \
                           away_name if pa >= ph and pa >= pd else "Draw"

    # Normalize probabilities
    ph = int(result.get("winProbHome", 40))
    pd = int(result.get("winProbDraw", 25))
    pa = int(result.get("winProbAway", 35))
    total = ph + pd + pa
    if total != 100:
        result["winProbHome"] = round(ph * 100 / total)
        result["winProbDraw"] = round(pd * 100 / total)
        result["winProbAway"] = 100 - result["winProbHome"] - result["winProbDraw"]

    return result


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/status")
def status():
    groq_key = request.headers.get("X-Groq-Key", "").strip() or GROQ_API_KEY
    return jsonify({
        "groq":    bool(groq_key),
        "model":   GROQ_MODEL,
        "message": "Groq ready" if groq_key else "No Groq key — get free key at console.groq.com"
    })


@app.route("/api/teams")
def get_teams():
    """Return teams for a league — used by autocomplete."""
    af_key    = request.headers.get("X-AF-Key", "").strip()
    league_code = request.args.get("league", "PL")
    league_id = LEAGUE_IDS.get(league_code, 39)
    if not af_key:
        return jsonify({"error": "No API-Football key"}), 400
    try:
        data = af_get("teams", af_key, {"league": league_id, "season": CURRENT_SEASON})
        # Normalise to match old format expected by autocomplete
        teams = []
        for item in data.get("response", []):
            t = item.get("team", {})
            teams.append({
                "id":        t.get("id"),
                "name":      t.get("name", ""),
                "shortName": t.get("name", ""),
                "tla":       t.get("code", ""),
                "crest":     t.get("logo", ""),
            })
        return jsonify({"teams": teams})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/fixtures")
def get_fixtures():
    """Upcoming scheduled matches across top leagues."""
    af_key  = request.headers.get("X-AF-Key", "").strip()
    days    = int(request.args.get("days", 7))
    leagues = request.args.get("leagues", "PL,PD,BL1,SA,FL1,CL")
    if not af_key:
        return jsonify({"error": "No API-Football key"}), 400

    now       = datetime.now(timezone.utc)
    date_from = now.strftime("%Y-%m-%d")
    date_to   = (now + timedelta(days=days)).strftime("%Y-%m-%d")

    all_matches, errors = [], []
    for code in leagues.split(","):
        code = code.strip()
        lid  = LEAGUE_IDS.get(code)
        if not lid:
            continue
        try:
            data = af_get("fixtures", af_key, {
                "league": lid, "season": CURRENT_SEASON,
                "from": date_from, "to": date_to,
            })
            total = data.get("results", 0)
            print(f"[fixtures] {code} season={CURRENT_SEASON} {date_from}→{date_to}: {total} results")
            for f in data.get("response", []):
                fix    = f.get("fixture", {})
                status = fix.get("status", {}).get("short", "")
                if status in ("1H","HT","2H","ET","BT","P","INT","FT","AET","PEN","WO","CANC","ABD"):
                    continue
                lge  = f.get("league", {})
                home = f.get("teams", {}).get("home", {})
                away = f.get("teams", {}).get("away", {})
                all_matches.append({
                    "id":      fix.get("id"),
                    "utcDate": fix.get("date", ""),
                    "status":  fix.get("status", {}).get("short", ""),
                    "homeTeam": {
                        "id":    home.get("id"),
                        "name":  home.get("name", ""),
                        "crest": home.get("logo", ""),
                    },
                    "awayTeam": {
                        "id":    away.get("id"),
                        "name":  away.get("name", ""),
                        "crest": away.get("logo", ""),
                    },
                    "competition": {
                        "id":     lid,
                        "code":   code,
                        "name":   lge.get("name", code),
                        "emblem": lge.get("logo", ""),
                    },
                    "matchday": lge.get("round", ""),
                })
        except Exception as e:
            errors.append(f"{code}: {e}")

    all_matches.sort(key=lambda m: m.get("utcDate", ""))
    return jsonify({
        "matches":  all_matches,
        "dateFrom": date_from,
        "dateTo":   date_to,
        "errors":   errors,
        "count":    len(all_matches),
    })


@app.route("/api/analyze", methods=["POST"])
def analyze():
    body        = request.json or {}
    af_key      = request.headers.get("X-AF-Key", "").strip()
    groq_key    = request.headers.get("X-Groq-Key", "").strip()
    home_query  = body.get("home", "").strip()
    away_query  = body.get("away", "").strip()
    league_code = body.get("leagueId",   "PL")
    league_name = body.get("leagueName", "Premier League")
    match_date  = body.get("matchDate",  "")
    use_ai      = body.get("useAI", True)

    if not af_key:
        return jsonify({"error": "API-Football key required"}), 400
    if not home_query or not away_query:
        return jsonify({"error": "Both team names required"}), 400

    league_id = LEAGUE_IDS.get(league_code, 39)
    result = {}

    try:
        # 1. Get all teams in competition → fuzzy match
        teams_data = af_get("teams", af_key, {"league": league_id, "season": CURRENT_SEASON})
        teams = teams_data.get("response", [])

        ht_item = find_team(teams, home_query)
        at_item = find_team(teams, away_query)
        if not ht_item:
            return jsonify({"error": f'"{home_query}" not found in {league_name}. Try full official name.'}), 404
        if not at_item:
            return jsonify({"error": f'"{away_query}" not found in {league_name}. Try full official name.'}), 404

        ht = {
            "id":    ht_item["team"]["id"],
            "name":  ht_item["team"]["name"],
            "crest": ht_item["team"].get("logo", ""),
            "shortName": ht_item["team"]["name"],
        }
        at = {
            "id":    at_item["team"]["id"],
            "name":  at_item["team"]["name"],
            "crest": at_item["team"].get("logo", ""),
            "shortName": at_item["team"]["name"],
        }
        result.update({
            "homeTeam":  ht,
            "awayTeam":  at,
            "league":    {"id": league_code, "name": league_name},
            "matchDate": match_date,
        })

        # 2. Standings
        try:
            sd = af_get("standings", af_key, {"league": league_id, "season": CURRENT_SEASON})
            standings_list = sd.get("response", [{}])[0].get("league", {}).get("standings", [[]])[0]
            result["standings"]    = standings_list
            result["homeStanding"] = next((s for s in standings_list if s["team"]["id"] == ht["id"]), None)
            result["awayStanding"] = next((s for s in standings_list if s["team"]["id"] == at["id"]), None)
        except Exception as e:
            print(f"[standings] {e}")
            result["standings"] = result["homeStanding"] = result["awayStanding"] = None

        # 3. Recent fixtures (form)
        for key, team in [("home", ht), ("away", at)]:
            try:
                fd = af_get("fixtures", af_key, {
                    "team": team["id"], "season": CURRENT_SEASON,
                    "status": "FT", "last": 8
                })
                fixtures = fd.get("response", [])
                result[f"{key}Fixtures"] = fixtures
                result[f"{key}Form"]     = get_form_from_fixtures(fixtures, team["id"])
                # For backwards compat with chat context builder
                result[f"{key}Matches"]  = [_fixture_to_match(f) for f in fixtures]
            except Exception as e:
                print(f"[form {key}] {e}")
                result[f"{key}Fixtures"] = []
                result[f"{key}Form"]     = "N/A"
                result[f"{key}Matches"]  = []

        # 4. H2H
        try:
            h2h_data = af_get("fixtures/headtohead", af_key, {
                "h2h": f"{ht['id']}-{at['id']}",
                "last": 8, "status": "FT"
            })
            result["h2h"] = h2h_data.get("response", [])
        except Exception as e:
            print(f"[h2h] {e}")
            result["h2h"] = []

        # 5. Squads
        for key, team in [("home", ht), ("away", at)]:
            try:
                sq = af_get("players/squads", af_key, {"team": team["id"]})
                players_raw = sq.get("response", [{}])[0].get("players", [])
                result[f"{key}Players"] = [
                    {
                        "name":     p.get("name", ""),
                        "position": p.get("position", ""),
                        "nationality": "",
                        "age":      p.get("age", ""),
                        "number":   p.get("number", ""),
                    }
                    for p in players_raw
                ]
            except Exception as e:
                print(f"[squad {key}] {e}")
                result[f"{key}Players"] = []

        # 6. AI Prediction
        effective_groq = groq_key or GROQ_API_KEY
        if use_ai and effective_groq:
            try:
                result["aiPrediction"] = ai_predict(result, effective_groq)
            except Exception as e:
                print(f"[ai] {e}")
                result["aiPrediction"] = {"error": str(e)}
        else:
            result["aiPrediction"] = None

        return jsonify(result)

    except Exception as e:
        print(f"[analyze] {e}")
        return jsonify({"error": str(e)}), 500


def _fixture_to_match(f):
    """Convert api-football fixture to the shape expected by the chat context builder."""
    teams = f.get("teams", {})
    goals = f.get("goals", {})
    return {
        "utcDate":  f.get("fixture", {}).get("date", ""),
        "homeTeam": {"id": teams.get("home", {}).get("id"), "name": teams.get("home", {}).get("name", "")},
        "awayTeam": {"id": teams.get("away", {}).get("id"), "name": teams.get("away", {}).get("name", "")},
        "score":    {"fullTime": {"home": goals.get("home"), "away": goals.get("away")}},
        "competition": {"name": f.get("league", {}).get("name", "")},
    }


@app.route("/api/chat", methods=["POST"])
def chat():
    body     = request.json or {}
    groq_key = request.headers.get("X-Groq-Key", "").strip()
    messages = body.get("messages", [])
    system   = body.get("system", "You are a football analytics expert. Be concise and factual.")
    if not messages:
        return jsonify({"error": "No messages"}), 400
    try:
        full  = [{"role": "system", "content": system}] + messages
        reply = groq_chat(full, groq_key, temperature=0.2, max_tokens=600, as_json=False)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*55}")
    print(f"  ⚽  ScoutAI  —  http://localhost:{port}")
    print(f"  Data: api-football.com v3 (100 req/day free)")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
