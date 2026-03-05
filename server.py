#!/usr/bin/env python3
"""
ScoutAI — Football Analytics Bot
Data: football-data.org (free)
AI:   Groq API (free tier, no credit card)
Host: Railway.app (free)

HOW TO RUN LOCALLY:
  pip install -r requirements.txt
  set GROQ_API_KEY=your_key_here     (Windows)
  export GROQ_API_KEY=your_key_here  (Mac/Linux)
  python server.py

HOW TO DEPLOY (no terminal for users):
  Push to GitHub → connect to Railway.app → set env vars → done.
  Friends just open the Railway URL.
"""

import json
import os
import re
import requests
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder=".")
CORS(app)

# ── CONFIG ───────────────────────────────────────────────────────────────────
FD_BASE    = "https://api.football-data.org/v4"
GROQ_BASE  = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.1-8b-instant"   # fast, free, great for JSON

# Groq key: set via env var GROQ_API_KEY, or user passes it from the frontend
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")


# ── football-data.org ────────────────────────────────────────────────────────

def fd_get(path, api_key):
    r = requests.get(FD_BASE + path,
                     headers={"X-Auth-Token": api_key}, timeout=12)
    if not r.ok:
        try:
            msg = r.json().get("message", f"HTTP {r.status_code}")
        except Exception:
            msg = f"HTTP {r.status_code}"
        raise Exception(msg)
    return r.json()


def find_team(teams, query):
    q = query.lower().strip()
    for t in teams:
        for f in [t.get("name",""), t.get("shortName",""), t.get("tla","")]:
            if f.lower() == q:
                return t
    for t in teams:
        for f in [t.get("name",""), t.get("shortName","")]:
            if q in f.lower() or f.lower() in q:
                return t
    q0 = q.split()[0]
    for t in teams:
        if any(w.startswith(q0) for w in t.get("name","").lower().split()):
            return t
    return None


def get_form(matches, team_id):
    out = []
    for m in reversed(matches):
        is_home = m.get("homeTeam", {}).get("id") == team_id
        ft = m.get("score", {}).get("fullTime", {})
        hg, ag = ft.get("home"), ft.get("away")
        if hg is None or ag is None:
            continue
        gs, gc = (hg, ag) if is_home else (ag, hg)
        out.append("W" if gs > gc else "L" if gs < gc else "D")
    return "-".join(out) if out else "N/A"


# ── Groq API ─────────────────────────────────────────────────────────────────

def groq_chat(messages, groq_key, temperature=0.3, max_tokens=1200):
    """Call Groq's OpenAI-compatible API."""
    key = groq_key or GROQ_API_KEY
    if not key:
        raise Exception(
            "No Groq API key. Get a free key at console.groq.com "
            "and enter it in the app."
        )
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},  # force JSON output
    }
    try:
        r = requests.post(
            f"{GROQ_BASE}/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
    except requests.exceptions.ConnectionError:
        raise Exception("Network error reaching Groq API.")

    if not r.ok:
        try:
            err = r.json().get("error", {}).get("message", r.text[:300])
        except Exception:
            err = r.text[:300]
        raise Exception(f"Groq API {r.status_code}: {err}")

    return r.json()["choices"][0]["message"]["content"]


def groq_chat_plain(messages, groq_key, temperature=0.3, max_tokens=600):
    """Groq call without JSON format — for natural chat replies."""
    key = groq_key or GROQ_API_KEY
    if not key:
        raise Exception("No Groq API key.")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = requests.post(
        f"{GROQ_BASE}/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )
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
        raise ValueError("No JSON object in response")
    depth = end = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if not end:
        raise ValueError("Unclosed JSON")
    return json.loads(text[start:end + 1])


# ── AI Prediction ─────────────────────────────────────────────────────────────

def ai_predict(data, groq_key):
    home      = data["homeTeam"]
    away      = data["awayTeam"]
    hs        = data.get("homeStanding") or {}
    as_       = data.get("awayStanding") or {}
    h2h       = data.get("h2h", [])
    home_name = home["name"]
    away_name = away["name"]

    h2h_txt = "\n".join(
        f"  {m.get('homeTeam',{}).get('name','?')} "
        f"{m.get('score',{}).get('fullTime',{}).get('home','?')}-"
        f"{m.get('score',{}).get('fullTime',{}).get('away','?')} "
        f"{m.get('awayTeam',{}).get('name','?')} "
        f"({m.get('utcDate','')[:10]})"
        for m in h2h[:6]
    ) or "  No H2H data"

    def fmt_results(matches, team_id):
        lines = []
        for m in reversed(matches[:5]):
            is_home = m.get("homeTeam", {}).get("id") == team_id
            ft = m.get("score", {}).get("fullTime", {})
            hg = ft.get("home", "?")
            ag = ft.get("away", "?")
            gs = hg if is_home else ag
            gc = ag if is_home else hg
            opp = m.get("awayTeam" if is_home else "homeTeam", {}).get("name", "?")
            try:
                res = "WIN" if int(gs) > int(gc) else "LOSS" if int(gs) < int(gc) else "DRAW"
            except Exception:
                res = "?"
            lines.append(f"  {res} {gs}-{gc} vs {opp}")
        return "\n".join(lines) if lines else "  No data"

    home_results = fmt_results(data.get("homeMatches", []), home.get("id"))
    away_results = fmt_results(data.get("awayMatches", []), away.get("id"))

    system_msg = (
        "You are a professional football analyst with 20 years of experience. "
        "You make single definitive predictions — never hedge or list multiple options. "
        "You always pick exactly ONE winner based on the data. "
        "Return ONLY a valid JSON object, no other text."
    )

    prompt = f"""Analyze this football match and give your single definitive prediction.

=== MATCH ===
{home_name} (HOME) vs {away_name} (AWAY)
Competition: {data["league"]["name"]}

{home_name}:
  Position: #{hs.get("position","?")} | P{hs.get("playedGames","?")} W{hs.get("won","?")} D{hs.get("draw","?")} L{hs.get("lost","?")}
  Goals: scored {hs.get("goalsFor","?")} conceded {hs.get("goalsAgainst","?")} | Points: {hs.get("points","?")}
  Form: {data.get("homeForm","?")}
  Last 5:
{home_results}

{away_name}:
  Position: #{as_.get("position","?")} | P{as_.get("playedGames","?")} W{as_.get("won","?")} D{as_.get("draw","?")} L{as_.get("lost","?")}
  Goals: scored {as_.get("goalsFor","?")} conceded {as_.get("goalsAgainst","?")} | Points: {as_.get("points","?")}
  Form: {data.get("awayForm","?")}
  Last 5:
{away_results}

H2H:
{h2h_txt}

Return this JSON with your DEFINITIVE prediction:
{{
  "winner": "PICK EXACTLY ONE: {home_name} OR {away_name} OR Draw",
  "score": "e.g. 2-1",
  "confidence": "High or Medium or Low",
  "btts": "Yes or No",
  "over25": "Yes or No",
  "winProbHome": <integer>,
  "winProbDraw": <integer>,
  "winProbAway": <integer>,
  "keyFactor": "The single most decisive reason for your prediction",
  "analysis": "200 words: why this team wins, what the stats show, form, H2H, tactical edge. Be direct and confident.",
  "homeStrengths": ["strength 1", "strength 2", "strength 3"],
  "awayStrengths": ["strength 1", "strength 2", "strength 3"],
  "riskFactor": "The one thing that could make this prediction wrong"
}}

RULES:
- winner = exactly "{home_name}" OR "{away_name}" OR "Draw" — nothing else
- winProbHome + winProbDraw + winProbAway = 100 exactly
- Pick based on league position, form, H2H record, and goals data above"""

    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user",   "content": prompt},
    ]

    raw = groq_chat(messages, groq_key)
    print(f"[Groq raw]: {raw[:300]}")
    result = extract_json(raw)

    # Safety: validate winner
    valid = [home_name, away_name, "Draw"]
    if result.get("winner") not in valid:
        ph = result.get("winProbHome", 0)
        pd = result.get("winProbDraw", 0)
        pa = result.get("winProbAway", 0)
        if ph >= pa and ph >= pd:
            result["winner"] = home_name
        elif pa >= ph and pa >= pd:
            result["winner"] = away_name
        else:
            result["winner"] = "Draw"

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


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/status")
def status():
    groq_key = request.headers.get("X-Groq-Key", "").strip() or GROQ_API_KEY
    groq_ready = bool(groq_key)
    return jsonify({
        "groq": groq_ready,
        "model": GROQ_MODEL,
        "message": "Groq ready" if groq_ready else "No Groq API key — get one free at console.groq.com"
    })


@app.route("/api/teams")
def get_teams():
    fd_key    = request.headers.get("X-FD-Key", "").strip()
    league_id = request.args.get("league", "PL")
    if not fd_key:
        return jsonify({"error": "No football-data.org key"}), 400
    try:
        return jsonify(fd_get(f"/competitions/{league_id}/teams", fd_key))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/fixtures")
def get_fixtures():
    from datetime import datetime, timedelta, timezone
    fd_key    = request.headers.get("X-FD-Key", "").strip()
    leagues   = request.args.get("leagues", "PL,PD,BL1,SA,FL1,CL")
    days      = int(request.args.get("days", "7"))
    if not fd_key:
        return jsonify({"error": "No API key"}), 400

    now       = datetime.now(timezone.utc)
    date_from = now.strftime("%Y-%m-%d")
    date_to   = (now + timedelta(days=days)).strftime("%Y-%m-%d")

    all_matches, errors = [], []
    for lid in leagues.split(","):
        lid = lid.strip()
        try:
            data = fd_get(
                f"/competitions/{lid}/matches?status=SCHEDULED"
                f"&dateFrom={date_from}&dateTo={date_to}",
                fd_key
            )
            comp = data.get("competition", {})
            for m in data.get("matches", []):
                all_matches.append({
                    "id":       m.get("id"),
                    "utcDate":  m.get("utcDate", ""),
                    "status":   m.get("status", ""),
                    "homeTeam": m.get("homeTeam", {}),
                    "awayTeam": m.get("awayTeam", {}),
                    "competition": {
                        "id":     comp.get("id", lid),
                        "name":   comp.get("name", lid),
                        "code":   comp.get("code", lid),
                        "emblem": comp.get("emblem", ""),
                    },
                    "matchday": m.get("matchday"),
                })
        except Exception as e:
            errors.append(f"{lid}: {e}")

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
    body       = request.json or {}
    fd_key     = request.headers.get("X-FD-Key", "").strip()
    groq_key   = request.headers.get("X-Groq-Key", "").strip()
    home_query = body.get("home", "").strip()
    away_query = body.get("away", "").strip()
    league_id  = body.get("leagueId",   "PL")
    league_name= body.get("leagueName", "Premier League")
    match_date = body.get("matchDate",  "")
    use_ai     = body.get("useAI", True)

    if not fd_key:
        return jsonify({"error": "football-data.org API key required"}), 400
    if not home_query or not away_query:
        return jsonify({"error": "Both team names required"}), 400

    result = {}
    try:
        # 1. Teams
        teams = fd_get(f"/competitions/{league_id}/teams", fd_key).get("teams", [])
        ht = find_team(teams, home_query)
        at = find_team(teams, away_query)
        if not ht:
            return jsonify({"error": f'"{home_query}" not found in {league_name}.'}), 404
        if not at:
            return jsonify({"error": f'"{away_query}" not found in {league_name}.'}), 404
        result.update({"homeTeam": ht, "awayTeam": at,
                        "league": {"id": league_id, "name": league_name},
                        "matchDate": match_date})

        # 2. Standings
        try:
            sd   = fd_get(f"/competitions/{league_id}/standings", fd_key)
            rows = next(
                (s.get("table", []) for s in sd.get("standings", []) if s.get("type") == "TOTAL"),
                (sd.get("standings") or [{}])[0].get("table", [])
            )
            result["standings"]    = rows
            result["homeStanding"] = next((r for r in rows if r["team"]["id"] == ht["id"]), None)
            result["awayStanding"] = next((r for r in rows if r["team"]["id"] == at["id"]), None)
        except Exception as e:
            print(f"[standings] {e}")
            result["standings"] = result["homeStanding"] = result["awayStanding"] = None

        # 3. Form
        for key, team in [("home", ht), ("away", at)]:
            try:
                ms = fd_get(f"/teams/{team['id']}/matches?status=FINISHED&limit=8", fd_key).get("matches", [])
                result[f"{key}Matches"] = ms
                result[f"{key}Form"]    = get_form(ms, team["id"])
            except Exception as e:
                print(f"[form {key}] {e}")
                result[f"{key}Matches"] = []
                result[f"{key}Form"]    = "N/A"

        # 4. H2H
        try:
            all_m = fd_get(f"/teams/{ht['id']}/matches?status=FINISHED&limit=100", fd_key).get("matches", [])
            ids   = {ht["id"], at["id"]}
            result["h2h"] = [
                m for m in all_m
                if {m.get("homeTeam", {}).get("id"), m.get("awayTeam", {}).get("id")} == ids
            ][:8]
        except Exception as e:
            print(f"[h2h] {e}")
            result["h2h"] = []

        # 5. Squads
        for key, team in [("home", ht), ("away", at)]:
            try:
                result[f"{key}Players"] = fd_get(f"/teams/{team['id']}", fd_key).get("squad", [])
            except Exception as e:
                print(f"[squad {key}] {e}")
                result[f"{key}Players"] = []

        # 6. AI via Groq
        effective_key = groq_key or GROQ_API_KEY
        if use_ai and effective_key:
            try:
                result["aiPrediction"] = ai_predict(result, effective_key)
            except Exception as e:
                print(f"[ai] {e}")
                result["aiPrediction"] = {"error": str(e)}
        else:
            result["aiPrediction"] = None

        return jsonify(result)

    except Exception as e:
        print(f"[analyze] {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    body     = request.json or {}
    groq_key = request.headers.get("X-Groq-Key", "").strip()
    messages = body.get("messages", [])
    system   = body.get("system", "You are a football analytics expert. Be concise.")
    if not messages:
        return jsonify({"error": "No messages"}), 400
    try:
        full  = [{"role": "system", "content": system}] + messages
        reply = groq_chat_plain(full, groq_key, temperature=0.2, max_tokens=600)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*55}")
    print(f"  ⚽  ScoutAI  —  http://localhost:{port}")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
