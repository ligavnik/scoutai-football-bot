#!/usr/bin/env python3
"""
ScoutAI — Football Analytics Bot
Keys live on the SERVER (env vars) — users register nothing.
Smart caching = no wasted API requests on refresh.

LOCAL:
  pip install -r requirements.txt
  set FD_KEY=your_football_data_key
  set GROQ_API_KEY=your_groq_key
  python server.py  →  http://localhost:5000

RAILWAY DEPLOY:
  Set env vars in Railway dashboard:
    FD_KEY        = your football-data.org key
    GROQ_API_KEY  = your Groq key
  Push to GitHub → connect Railway → done.
  Users just open the URL. Zero setup on their end.
"""

import json, os, re, time, hashlib, pickle, glob, requests

# Auto-load .env file — tries multiple locations
def _load_dotenv():
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        os.path.join(os.getcwd(), ".env"),
        ".env",
    ]
    for env_path in candidates:
        if os.path.exists(env_path):
            print(f"[.env] Loading from: {env_path}")
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and not os.environ.get(key):
                        os.environ[key] = val
                        print(f"[.env] Set {key}={'***' if 'KEY' in key else val}")
            return
    print("[.env] No .env file found — using environment variables only")
_load_dotenv()
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder=os.path.dirname(os.path.abspath(__file__)))
CORS(app)

# ── SERVER-SIDE KEYS — read fresh each request to avoid load-order issues ────
def get_fd_key():   return os.environ.get("FD_KEY", "").strip()
def get_groq_key(): return os.environ.get("GROQ_API_KEY", "").strip()

FD_BASE   = "https://api.football-data.org/v4"
GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_MODEL = "llama-3.1-8b-instant"

# Auto-detect current season
_now = datetime.now(timezone.utc)
CURRENT_SEASON = _now.year if _now.month >= 7 else _now.year - 1

LEAGUE_MAP = {
    "PL":  {"name": "Premier League",        "id": "PL"},
    "PD":  {"name": "La Liga",               "id": "PD"},
    "BL1": {"name": "Bundesliga",            "id": "BL1"},
    "SA":  {"name": "Serie A",               "id": "SA"},
    "FL1": {"name": "Ligue 1",               "id": "FL1"},
    "CL":  {"name": "Champions League",      "id": "CL"},
    "WC":  {"name": "FIFA World Cup",        "id": "WC"},
    "EC":  {"name": "European Championship", "id": "EC"},
}


# ── CACHE ─────────────────────────────────────────────────────────────────────
# Persistent file-based cache — survives server restarts.
# Cache folder is /tmp (works on Railway, Heroku, and locally).

CACHE_DIR = "/tmp/scoutai_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def _cache_ttl(key):
    if key.startswith("fixtures"):  return 1800   # 30 min  — fixtures change rarely
    if key.startswith("standings"): return 3600   # 1 hour
    if key.startswith("teams"):     return 86400  # 24 hours — squads rarely change
    if key.startswith("analyze"):   return 1800   # 30 min per match pair
    if key.startswith("h2h"):       return 86400  # 24 hours
    if key.startswith("form"):      return 3600   # 1 hour
    if key.startswith("squad"):     return 86400  # 24 hours
    return 1800

def _cache_file(key):
    safe = hashlib.md5(key.encode()).hexdigest()
    return os.path.join(CACHE_DIR, f"{safe}.pkl")

def cache_get(key):
    path = _cache_file(key)
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                ts, data = pickle.load(f)
            if time.time() - ts < _cache_ttl(key):
                return data
            os.remove(path)  # expired
    except Exception:
        pass
    return None

def cache_set(key, data):
    path = _cache_file(key)
    try:
        with open(path, "wb") as f:
            pickle.dump((time.time(), data), f)
    except Exception as e:
        print(f"[cache write error] {e}")


# ── FOOTBALL-DATA.ORG ─────────────────────────────────────────────────────────

def fd_get(path, params=None):
    if not get_fd_key():
        raise Exception("No football-data.org key configured on server.")
    headers = {"X-Auth-Token": get_fd_key()}
    r = requests.get(f"{FD_BASE}/{path.lstrip('/')}", headers=headers,
                     params=params or {}, timeout=12)
    if not r.ok:
        try:    msg = r.json().get("message", f"HTTP {r.status_code}")
        except: msg = f"HTTP {r.status_code}"
        raise Exception(msg)
    return r.json()


def find_team(teams, query):
    q = query.lower().strip()
    for t in teams:
        for f in [t.get("name",""), t.get("shortName",""), t.get("tla","")]:
            if f.lower() == q: return t
    for t in teams:
        for f in [t.get("name",""), t.get("shortName","")]:
            if q in f.lower() or f.lower() in q: return t
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
        if hg is None or ag is None: continue
        gs, gc = (hg, ag) if is_home else (ag, hg)
        out.append("W" if gs > gc else "L" if gs < gc else "D")
    return "-".join(out) if out else "N/A"


def fmt_recent(matches, team_id, n=5):
    lines = []
    for m in reversed(matches[:n]):
        is_home = m.get("homeTeam", {}).get("id") == team_id
        ft = m.get("score", {}).get("fullTime", {})
        hg = ft.get("home","?"); ag = ft.get("away","?")
        gs = hg if is_home else ag; gc = ag if is_home else hg
        opp = m.get("awayTeam" if is_home else "homeTeam", {}).get("name","?")
        date = m.get("utcDate","")[:10]
        try:    res = "WIN" if int(gs)>int(gc) else "LOSS" if int(gs)<int(gc) else "DRAW"
        except: res = "?"
        lines.append(f"  {res} {gs}-{gc} vs {opp} ({date})")
    return "\n".join(lines) if lines else "  No data"


# ── GROQ AI ───────────────────────────────────────────────────────────────────

def groq_chat(messages, temperature=0.3, max_tokens=1400, as_json=True):
    if not get_groq_key():
        raise Exception("No Groq API key configured on server.")
    headers = {"Authorization": f"Bearer {get_groq_key()}",
               "Content-Type": "application/json"}
    payload = {"model": GROQ_MODEL, "messages": messages,
               "temperature": temperature, "max_tokens": max_tokens}
    if as_json:
        payload["response_format"] = {"type": "json_object"}
    r = requests.post(f"{GROQ_BASE}/chat/completions", headers=headers,
                      json=payload, timeout=30)
    if not r.ok:
        try:    err = r.json().get("error", {}).get("message", r.text[:300])
        except: err = r.text[:300]
        raise Exception(f"Groq {r.status_code}: {err}")
    return r.json()["choices"][0]["message"]["content"]


def extract_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
    if m: text = m.group(1).strip()
    start = text.find("{")
    if start == -1: raise ValueError("No JSON found")
    depth = end = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{": depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0: end = i; break
    return json.loads(text[start:end+1])


# ── AI PREDICTION ─────────────────────────────────────────────────────────────

def ai_predict(data):
    home_name = data["homeTeam"]["name"]
    away_name = data["awayTeam"]["name"]
    hs  = data.get("homeStanding") or {}
    as_ = data.get("awayStanding") or {}

    h2h_lines = []
    for m in data.get("h2h", [])[:6]:
        ft = m.get("score",{}).get("fullTime",{})
        h2h_lines.append(
            f"  {m.get('homeTeam',{}).get('name','?')} "
            f"{ft.get('home','?')}-{ft.get('away','?')} "
            f"{m.get('awayTeam',{}).get('name','?')} "
            f"({m.get('utcDate','')[:10]})"
        )
    h2h_txt      = "\n".join(h2h_lines) or "  No H2H data"
    home_recent  = fmt_recent(data.get("homeMatches",[]), data["homeTeam"]["id"])
    away_recent  = fmt_recent(data.get("awayMatches",[]), data["awayTeam"]["id"])

    prompt = f"""Analyze this match and return your single definitive prediction as JSON.

MATCH: {home_name} (HOME) vs {away_name} (AWAY)
Competition: {data["league"]["name"]}

{home_name}: #{hs.get("position","?")} | P{hs.get("playedGames","?")} W{hs.get("won","?")} D{hs.get("draw","?")} L{hs.get("lost","?")} | GF:{hs.get("goalsFor","?")} GA:{hs.get("goalsAgainst","?")} | Pts:{hs.get("points","?")} | Form:{data.get("homeForm","?")}
Last 5:\n{home_recent}

{away_name}: #{as_.get("position","?")} | P{as_.get("playedGames","?")} W{as_.get("won","?")} D{as_.get("draw","?")} L{as_.get("lost","?")} | GF:{as_.get("goalsFor","?")} GA:{as_.get("goalsAgainst","?")} | Pts:{as_.get("points","?")} | Form:{data.get("awayForm","?")}
Last 5:\n{away_recent}

H2H:\n{h2h_txt}

Return ONLY this JSON:
{{
  "winner": "EXACTLY {home_name} OR {away_name} OR Draw",
  "score": "2-1",
  "confidence": "High or Medium or Low",
  "btts": "Yes or No",
  "over25": "Yes or No",
  "winProbHome": 45,
  "winProbDraw": 25,
  "winProbAway": 30,
  "keyFactor": "single most decisive reason",
  "analysis": "200 word expert analysis, direct and confident",
  "homeStrengths": ["data-based strength","strength","strength"],
  "awayStrengths": ["data-based strength","strength","strength"],
  "riskFactor": "what could make this prediction wrong"
}}
Rules: winner = exactly one name or Draw. Probabilities sum to 100."""

    raw = groq_chat([
        {"role":"system","content":"You are a professional football analyst. Pick ONE definitive winner. Return only valid JSON."},
        {"role":"user","content":prompt}
    ])
    result = extract_json(raw)

    # Safety: validate winner
    valid = [home_name, away_name, "Draw"]
    if result.get("winner") not in valid:
        ph = result.get("winProbHome",0)
        pa = result.get("winProbAway",0)
        pd = result.get("winProbDraw",0)
        result["winner"] = home_name if ph>=pa and ph>=pd else away_name if pa>=ph and pa>=pd else "Draw"

    # Normalize probabilities
    ph,pd,pa = int(result.get("winProbHome",40)), int(result.get("winProbDraw",25)), int(result.get("winProbAway",35))
    total = ph+pd+pa
    if total != 100:
        result["winProbHome"] = round(ph*100/total)
        result["winProbDraw"] = round(pd*100/total)
        result["winProbAway"] = 100-result["winProbHome"]-result["winProbDraw"]

    return result


# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "index.html")

@app.route("/favicon.ico")
def favicon():
    return "", 204  # No content — stops 404 spam


@app.route("/api/debug")
def debug():
    """Shows config state — remove this route before making the app public."""
    cache_files = len(glob.glob(os.path.join(CACHE_DIR, "*.pkl")))
    return jsonify({
        "FD_KEY_set":       bool(get_fd_key()),
        "FD_KEY_length":    len(get_fd_key()),
        "GROQ_KEY_set":     bool(get_groq_key()),
        "GROQ_KEY_length":  len(get_groq_key()),
        "cwd":              os.getcwd(),
        "env_file_exists":  os.path.exists(os.path.join(os.getcwd(), ".env")),
        "season":           CURRENT_SEASON,
        "cache_files":      cache_files,
    })


@app.route("/api/status")
def status():
    """Tell the frontend which features are available + cache stats."""
    try:
        cached_count = len(glob.glob(os.path.join(CACHE_DIR, "*.pkl")))
    except Exception:
        cached_count = 0

    return jsonify({
        "fdReady":    bool(get_fd_key()),
        "groqReady":  bool(get_groq_key()),
        "season":     CURRENT_SEASON,
        "cachedItems": cached_count,
        "message":    "OK" if get_fd_key() and get_groq_key() else "Some keys missing on server"
    })


@app.route("/api/teams")
def get_teams():
    league_code = request.args.get("league", "PL")
    cache_key   = f"teams_{league_code}"
    cached = cache_get(cache_key)
    if cached:
        print(f"[cache HIT] {cache_key}")
        return jsonify(cached)
    try:
        data = fd_get(f"competitions/{league_code}/teams")
        cache_set(cache_key, data)
        print(f"[cache SET] {cache_key}")
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/fixtures")
def get_fixtures():
    days      = int(request.args.get("days", 7))
    cache_key = f"fixtures_{days}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    cached = cache_get(cache_key)
    if cached:
        print(f"[cache HIT] fixtures ({cached['count']} matches)")
        return jsonify(cached)

    now       = datetime.now(timezone.utc)
    date_from = now.strftime("%Y-%m-%d")
    date_to   = (now + timedelta(days=days)).strftime("%Y-%m-%d")

    # Single API call — returns ALL matches across all subscribed competitions
    try:
        data = fd_get("matches", {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"})
    except Exception as e:
        print(f"[fixtures ERR] {e}")
        return jsonify({"error": str(e), "matches": [], "count": 0}), 400

    all_matches = []
    for m in data.get("matches", []):
        comp = m.get("competition", {})
        all_matches.append({
            "id":       m.get("id"),
            "utcDate":  m.get("utcDate", ""),
            "status":   m.get("status", ""),
            "homeTeam": m.get("homeTeam", {}),
            "awayTeam": m.get("awayTeam", {}),
            "competition": {
                "id":     comp.get("id", ""),
                "code":   comp.get("code", ""),
                "name":   comp.get("name", ""),
                "emblem": comp.get("emblem", ""),
            },
            "matchday": m.get("matchday"),
        })

    all_matches.sort(key=lambda m: m.get("utcDate", ""))
    print(f"[fixtures] {date_from} → {date_to}: {len(all_matches)} matches total")

    result = {"matches": all_matches, "dateFrom": date_from, "dateTo": date_to,
              "errors": [], "count": len(all_matches)}
    if all_matches:
        cache_set(cache_key, result)
    return jsonify(result)


@app.route("/api/analyze", methods=["POST"])
def analyze():
    body        = request.json or {}
    home_query  = body.get("home","").strip()
    away_query  = body.get("away","").strip()
    league_code = body.get("leagueId","PL")
    league_name = body.get("leagueName","Premier League")
    match_date  = body.get("matchDate","")
    use_ai      = body.get("useAI", True)

    if not home_query or not away_query:
        return jsonify({"error": "Both team names required"}), 400
    if not get_fd_key():
        return jsonify({"error": "Football data key not configured on server."}), 500

    # Cache key based on the match
    cache_key = f"analyze_{league_code}_{home_query.lower()}_{away_query.lower()}"
    cached = cache_get(cache_key)
    if cached:
        print(f"[cache HIT] {cache_key}")
        return jsonify(cached)

    result = {}
    try:
        # 1. Teams (cached separately)
        teams_cache_key = f"teams_{league_code}"
        teams_data = cache_get(teams_cache_key)
        if not teams_data:
            teams_data = fd_get(f"competitions/{league_code}/teams")
            cache_set(teams_cache_key, teams_data)

        teams = teams_data.get("teams", [])
        ht = find_team(teams, home_query)
        at = find_team(teams, away_query)
        if not ht: return jsonify({"error": f'"{home_query}" not found in {league_name}.'}), 404
        if not at: return jsonify({"error": f'"{away_query}" not found in {league_name}.'}), 404

        result.update({"homeTeam": ht, "awayTeam": at,
                        "league": {"id": league_code, "name": league_name},
                        "matchDate": match_date})

        # 2. Standings (cached)
        stand_key = f"standings_{league_code}"
        sd = cache_get(stand_key)
        if not sd:
            sd = fd_get(f"competitions/{league_code}/standings")
            cache_set(stand_key, sd)
        try:
            rows = next((s.get("table",[]) for s in sd.get("standings",[]) if s.get("type")=="TOTAL"),
                        (sd.get("standings") or [{}])[0].get("table",[]))
            result["standings"]    = rows
            result["homeStanding"] = next((r for r in rows if r["team"]["id"]==ht["id"]), None)
            result["awayStanding"] = next((r for r in rows if r["team"]["id"]==at["id"]), None)
        except Exception as e:
            print(f"[standings] {e}")
            result["standings"] = result["homeStanding"] = result["awayStanding"] = None

        # 3. Recent form (cached per team)
        for key, team in [("home", ht), ("away", at)]:
            form_key = f"form_{team['id']}"
            ms = cache_get(form_key)
            if not ms:
                fd_data = fd_get(f"teams/{team['id']}/matches",
                                 {"status":"FINISHED","limit":8})
                ms = fd_data.get("matches",[])
                cache_set(form_key, ms)
            result[f"{key}Matches"] = ms
            result[f"{key}Form"]    = get_form(ms, team["id"])

        # 4. H2H (cached)
        h2h_key = f"h2h_{min(ht['id'],at['id'])}_{max(ht['id'],at['id'])}"
        h2h = cache_get(h2h_key)
        if not h2h:
            all_m = fd_get(f"teams/{ht['id']}/matches",
                           {"status":"FINISHED","limit":100}).get("matches",[])
            ids   = {ht["id"], at["id"]}
            h2h   = [m for m in all_m
                     if {m.get("homeTeam",{}).get("id"), m.get("awayTeam",{}).get("id")} == ids][:8]
            cache_set(h2h_key, h2h)
        result["h2h"] = h2h

        # 5. Squads (cached per team)
        for key, team in [("home", ht), ("away", at)]:
            sq_key = f"squad_{team['id']}"
            sq = cache_get(sq_key)
            if not sq:
                sq = fd_get(f"teams/{team['id']}").get("squad",[])
                cache_set(sq_key, sq)
            result[f"{key}Players"] = sq

        # 6. AI prediction (Groq)
        if use_ai and get_groq_key():
            try:
                result["aiPrediction"] = ai_predict(result)
            except Exception as e:
                print(f"[ai] {e}")
                result["aiPrediction"] = {"error": str(e)}
        else:
            result["aiPrediction"] = None

        cache_set(cache_key, result)
        return jsonify(result)

    except Exception as e:
        print(f"[analyze] {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    body     = request.json or {}
    messages = body.get("messages", [])
    system   = body.get("system", "You are a football analytics expert. Be concise and factual.")
    if not messages:
        return jsonify({"error": "No messages"}), 400
    try:
        reply = groq_chat([{"role":"system","content":system}]+messages,
                          temperature=0.2, max_tokens=600, as_json=False)
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*55}")
    print(f"  ⚽  ScoutAI  —  http://localhost:{port}")
    print(f"  Season: {CURRENT_SEASON}")
    print(f"  FD key:   {'✓ set' if get_fd_key() else '✗ missing — set FD_KEY env var'}")
    print(f"  Groq key: {'✓ set' if get_groq_key() else '✗ missing — set GROQ_API_KEY env var'}")
    print(f"{'='*55}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
