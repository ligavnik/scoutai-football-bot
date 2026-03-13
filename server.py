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

# Understat league names (free xG data, no key needed)
UNDERSTAT_LEAGUES = {
    "PL":  "EPL",
    "PD":  "La_Liga",
    "BL1": "Bundesliga",
    "SA":  "Serie_A",
    "FL1": "Ligue_1",
}

# football-data.org name → understat name mapping (fuzzy matched at runtime)
UNDERSTAT_TEAM_MAP = {
    "Manchester City":      "Manchester City",
    "Manchester United":    "Manchester United",
    "Arsenal":              "Arsenal",
    "Liverpool":            "Liverpool",
    "Chelsea":              "Chelsea",
    "Tottenham Hotspur":    "Tottenham",
    "Newcastle United":     "Newcastle United",
    "Aston Villa":          "Aston Villa",
    "Brighton & Hove Albion": "Brighton",
    "West Ham United":      "West Ham",
    "Brentford":            "Brentford",
    "Fulham":               "Fulham",
    "Wolverhampton Wanderers": "Wolverhampton Wanderers",
    "Nottingham Forest":    "Nottingham Forest",
    "Everton":              "Everton",
    "Crystal Palace":       "Crystal Palace",
    "Bournemouth":          "Bournemouth",
    "Leicester City":       "Leicester",
    "Ipswich Town":         "Ipswich",
    "Southampton":          "Southampton",
    "Real Madrid":          "Real Madrid",
    "FC Barcelona":         "Barcelona",
    "Atletico Madrid":      "Atletico Madrid",
    "Sevilla FC":           "Sevilla",
    "Real Betis":           "Real Betis",
    "Athletic Club":        "Athletic Club",
    "Villarreal CF":        "Villarreal",
    "Real Sociedad":        "Real Sociedad",
    "Bayern München":       "Bayern Munich",
    "Borussia Dortmund":    "Dortmund",
    "RB Leipzig":           "RB Leipzig",
    "Bayer 04 Leverkusen":  "Bayer Leverkusen",
    "Eintracht Frankfurt":  "Eintracht Frankfurt",
    "VfB Stuttgart":        "Stuttgart",
    "Juventus":             "Juventus",
    "AC Milan":             "Milan",
    "Inter Milan":          "Internazionale",
    "SSC Napoli":           "Napoli",
    "AS Roma":              "Roma",
    "Lazio":                "Lazio",
    "Atalanta BC":          "Atalanta",
    "Fiorentina":           "Fiorentina",
    "Paris Saint-Germain":  "Paris Saint-Germain",
    "Olympique de Marseille": "Marseille",
    "Olympique Lyonnais":   "Lyon",
    "AS Monaco":            "Monaco",
    "LOSC Lille":           "Lille",
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


# ── UNDERSTAT (free xG data — no API key) ────────────────────────────────────

def get_understat_team_xg(fd_team_name, league_code):
    """
    Scrape season xG stats for a team from understat.com.
    Returns dict with xG, xGA, xPTS, ppda, deep, scored, missed or None on failure.
    Cached 6 hours — understat updates once daily.
    """
    us_league = UNDERSTAT_LEAGUES.get(league_code)
    if not us_league:
        return None

    # Map football-data name to understat name
    us_name = UNDERSTAT_TEAM_MAP.get(fd_team_name)
    if not us_name:
        # Try fuzzy: strip common suffixes and match
        short = fd_team_name.replace(" FC","").replace(" CF","").replace(" AC","").strip()
        for fd, us in UNDERSTAT_TEAM_MAP.items():
            if short.lower() in fd.lower() or fd.lower() in short.lower():
                us_name = us
                break
    if not us_name:
        print(f"[understat] no name map for '{fd_team_name}'")
        return None

    cache_key = f"xg_{us_league}_{CURRENT_SEASON}"
    league_xg = cache_get(cache_key)

    if not league_xg:
        try:
            url = f"https://understat.com/league/{us_league}/{CURRENT_SEASON}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r = requests.get(url, headers=headers, timeout=15)
            if not r.ok:
                print(f"[understat] HTTP {r.status_code} for {url}")
                return None

            # Extract teamsData JSON from script tag
            match = re.search(r"var teamsData\s*=\s*JSON\.parse\('(.+?)'\)", r.text)
            if not match:
                print(f"[understat] teamsData not found in page")
                return None

            raw = match.group(1).encode().decode("unicode_escape")
            teams_data = json.loads(raw)
            league_xg = {}

            for team_id, team_info in teams_data.items():
                title = team_info.get("title", "")
                history = team_info.get("history", [])
                if not history:
                    continue
                # Sum up the season stats
                xg  = sum(float(m.get("xG",  0)) for m in history)
                xga = sum(float(m.get("xGA", 0)) for m in history)
                scored  = sum(int(m.get("scored",  0)) for m in history)
                missed  = sum(int(m.get("missed",  0)) for m in history)
                xpts    = sum(float(m.get("xpts",  0)) for m in history)
                deep    = sum(int(m.get("deep",    0)) for m in history)
                deep_a  = sum(int(m.get("deep_allowed", 0)) for m in history)
                # PPDA: passes per defensive action (lower = more pressing)
                ppda_att = sum(float(m.get("ppda", {}).get("att", 0)) for m in history)
                ppda_def = sum(float(m.get("ppda", {}).get("def", 1)) for m in history)
                ppda = round(ppda_att / ppda_def, 2) if ppda_def else None
                games = len(history)

                league_xg[title] = {
                    "xG":      round(xg,  2),
                    "xGA":     round(xga, 2),
                    "xGD":     round(xg - xga, 2),
                    "xPTS":    round(xpts, 1),
                    "xG_per":  round(xg  / games, 2) if games else 0,
                    "xGA_per": round(xga / games, 2) if games else 0,
                    "scored":  scored,
                    "missed":  missed,
                    "deep":    deep,
                    "deep_a":  deep_a,
                    "ppda":    ppda,
                    "games":   games,
                    # Over/under-performance
                    "xG_diff":  round(scored - xg,  2),
                    "xGA_diff": round(xga - missed, 2),
                }

            # Cache 6 hours — understat updates once daily
            _cache[f"xg_{us_league}_{CURRENT_SEASON}"] = (time.time() - (3600 * 18), league_xg)  # placeholder
            cache_key2 = f"xg_{us_league}_{CURRENT_SEASON}"
            cache_set(cache_key2, league_xg)
            league_xg = league_xg  # use the freshly built dict
            print(f"[understat] fetched {len(league_xg)} teams for {us_league} {CURRENT_SEASON}")

        except Exception as e:
            print(f"[understat] ERROR: {e}")
            return None

    # Find the team in the league data
    # Try exact match first, then fuzzy
    team_data = league_xg.get(us_name)
    if not team_data:
        for title, data in league_xg.items():
            if us_name.lower() in title.lower() or title.lower() in us_name.lower():
                team_data = data
                break
    if not team_data:
        print(f"[understat] '{us_name}' not found in {us_league} data. Available: {list(league_xg.keys())[:5]}")

    return team_data


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

def fmt_h2h_detail(matches, home_id, away_id):
    lines, home_w, away_w, draws = [], 0, 0, 0
    total_goals = []
    for m in matches[:8]:
        ft  = m.get("score",{}).get("fullTime",{})
        hg  = ft.get("home"); ag = ft.get("away")
        if hg is None or ag is None: continue
        is_home = m.get("homeTeam",{}).get("id") == home_id
        gs  = hg if is_home else ag
        gc  = ag if is_home else hg
        opp = m.get("awayTeam" if is_home else "homeTeam",{}).get("name","?")
        date = m.get("utcDate","")[:10]
        total = hg + ag
        total_goals.append(total)
        if gs > gc:   home_w += 1; res = "WIN"
        elif gs < gc: away_w += 1; res = "LOSS"
        else:         draws  += 1; res = "DRAW"
        lines.append(f"  {res} {gs}-{gc} vs {opp} ({date}) — {total} goals total")
    avg_goals = round(sum(total_goals)/len(total_goals), 1) if total_goals else "?"
    summary = f"  Record (last {len(lines)}): {home_w}W {draws}D {away_w}L | Avg goals/game: {avg_goals}"
    return "\n".join([summary] + lines) if lines else "  No H2H data"


def fmt_recent_deep(matches, team_id, n=8):
    lines = []
    home_pts = away_pts = home_g = away_g = 0
    home_n = away_n = 0
    for m in reversed(matches[:n]):
        is_home = m.get("homeTeam",{}).get("id") == team_id
        ft  = m.get("score",{}).get("fullTime",{})
        hg  = ft.get("home","?"); ag = ft.get("away","?")
        gs  = hg if is_home else ag
        gc  = ag if is_home else hg
        opp = m.get("awayTeam" if is_home else "homeTeam",{}).get("name","?")
        venue = "H" if is_home else "A"
        date  = m.get("utcDate","")[:10]
        try:
            res = "W" if int(gs)>int(gc) else "L" if int(gs)<int(gc) else "D"
            pts = 3 if res=="W" else 1 if res=="D" else 0
            if is_home: home_pts += pts; home_g += int(gs); home_n += 1
            else:       away_pts += pts; away_g += int(gs); away_n += 1
        except: res = "?"
        lines.append(f"  [{venue}] {res} {gs}-{gc} vs {opp} ({date})")
    home_avg = round(home_g/home_n,1) if home_n else "?"
    away_avg = round(away_g/away_n,1) if away_n else "?"
    split = f"  Home: {home_pts}pts/{home_n}g ({home_avg} goals/g) | Away: {away_pts}pts/{away_n}g ({away_avg} goals/g)"
    return "\n".join([split] + lines) if lines else "  No data"


def calc_avg_goals(matches, team_id, n=8):
    scored = conceded = count = 0
    for m in matches[:n]:
        is_home = m.get("homeTeam",{}).get("id") == team_id
        ft = m.get("score",{}).get("fullTime",{})
        hg = ft.get("home"); ag = ft.get("away")
        if hg is None or ag is None: continue
        scored   += hg if is_home else ag
        conceded += ag if is_home else hg
        count    += 1
    if not count: return None, None
    return round(scored/count, 2), round(conceded/count, 2)


def ai_predict(data):
    home_name = data["homeTeam"]["name"]
    away_name = data["awayTeam"]["name"]
    hs  = data.get("homeStanding") or {}
    as_ = data.get("awayStanding") or {}
    hxg = data.get("homeXG") or {}
    axg = data.get("awayXG") or {}
    league_name = data.get("league",{}).get("name","?")

    home_matches = data.get("homeMatches", [])
    away_matches = data.get("awayMatches", [])
    h2h_matches  = data.get("h2h", [])

    home_scored_avg, home_conceded_avg = calc_avg_goals(home_matches, data["homeTeam"]["id"])
    away_scored_avg, away_conceded_avg = calc_avg_goals(away_matches, data["awayTeam"]["id"])

    h2h_detail  = fmt_h2h_detail(h2h_matches, data["homeTeam"]["id"], data["awayTeam"]["id"])
    home_recent = fmt_recent_deep(home_matches, data["homeTeam"]["id"])
    away_recent = fmt_recent_deep(away_matches, data["awayTeam"]["id"])

    def xg_block(name, xg, standing):
        if not xg:
            return f"{name} xG: No data available"
        diff = xg.get("xG_diff", 0)
        if   diff > 2:   over_under = f"OVERPERFORMING xG by +{diff} goals — regression risk, real strength may be lower"
        elif diff > 1:   over_under = f"Slightly overperforming xG by +{diff} goals"
        elif diff < -2:  over_under = f"UNDERPERFORMING xG by {diff} goals — positive regression likely, better than results show"
        elif diff < -1:  over_under = f"Slightly underperforming xG by {diff} goals"
        else:            over_under = f"Performing in line with xG"
        ppda = xg.get("ppda")
        if   ppda and ppda < 8:  pressing = f"VERY HIGH pressing (PPDA:{ppda} — elite press, creates chaos)"
        elif ppda and ppda < 11: pressing = f"High pressing (PPDA:{ppda})"
        elif ppda and ppda < 14: pressing = f"Moderate pressing (PPDA:{ppda})"
        elif ppda:               pressing = f"Low pressing / passive block (PPDA:{ppda})"
        else:                    pressing = "Pressing data unavailable"
        xgd = xg.get("xGD", 0)
        if   xgd > 20: dom = "completely dominant"
        elif xgd > 10: dom = "strong"
        elif xgd > 3:  dom = "slight edge"
        elif xgd > -3: dom = "evenly matched"
        elif xgd > -10: dom = "under pressure"
        else:           dom = "struggling badly"
        return (f"{name}:\n"
                f"  xG/game: {xg['xG_per']} | xGA/game: {xg['xGA_per']} | Season xGD: {xgd} ({dom})\n"
                f"  {xg.get('scored','?')} goals scored vs {xg['xG']} xG expected — {over_under}\n"
                f"  Deep passes: {xg.get('deep','?')} | {pressing}\n"
                f"  Expected pts: {xg.get('xPTS','?')} vs actual {standing.get('points','?')} pts")

    # Implied goals: blend xG attack vs opponent xG defense
    def implied(att_xg, att_avg, def_xg, def_avg):
        vals = []
        if att_xg: vals.append(att_xg)
        if att_avg: vals.append(att_avg)
        if def_xg: vals.append(def_xg)
        if def_avg: vals.append(def_avg)
        return round(sum(vals)/len(vals), 2) if vals else "?"

    h_exp = implied(hxg.get("xG_per"), home_scored_avg,
                    axg.get("xGA_per"), away_conceded_avg)
    a_exp = implied(axg.get("xG_per"), away_scored_avg,
                    hxg.get("xGA_per"), home_conceded_avg)

    prompt = f"""You are an elite football data analyst. Analyze this match deeply and return a SPECIFIC, DATA-DRIVEN prediction. Use the implied goals to determine the realistic scoreline — do NOT default to generic 2-1.

MATCH: {home_name} (HOME) vs {away_name} (AWAY)
Competition: {league_name}

━━━ LEAGUE TABLE ━━━
{home_name}: #{hs.get("position","?")} | {hs.get("playedGames","?")} played | {hs.get("won","?")}W {hs.get("draw","?")}D {hs.get("lost","?")}L | GF:{hs.get("goalsFor","?")} GA:{hs.get("goalsAgainst","?")} | {hs.get("points","?")} pts | Form: {data.get("homeForm","?")}
{away_name}: #{as_.get("position","?")} | {as_.get("playedGames","?")} played | {as_.get("won","?")}W {as_.get("draw","?")}D {as_.get("lost","?")}L | GF:{as_.get("goalsFor","?")} GA:{as_.get("goalsAgainst","?")} | {as_.get("points","?")} pts | Form: {data.get("awayForm","?")}

━━━ xG ANALYTICS (most important data) ━━━
{xg_block(home_name, hxg, hs)}

{xg_block(away_name, axg, as_)}

IMPLIED EXPECTED GOALS THIS MATCH:
  {home_name} likely to score: ~{h_exp} goals
  {away_name} likely to score: ~{a_exp} goals
  Total expected: ~{round(h_exp + a_exp, 1) if isinstance(h_exp, float) and isinstance(a_exp, float) else "?"} goals

━━━ RECENT FORM — LAST 8 MATCHES ━━━
{home_name}:
{home_recent}

{away_name}:
{away_recent}

━━━ HEAD TO HEAD ━━━
{h2h_detail}

━━━ SCORING AVERAGES (last 8 games) ━━━
{home_name}: {home_scored_avg} scored / {home_conceded_avg} conceded per game
{away_name}: {away_scored_avg} scored / {away_conceded_avg} conceded per game

━━━ YOUR ANALYSIS TASK ━━━
Before predicting, reason through:
1. xG advantage: which team creates better quality chances?
2. Regression: is either team over/underperforming xG? Expect correction.
3. Defensive strength: compare xGA/game and goals conceded averages.
4. Form trajectory: is either team trending up or down?
5. H2H patterns: does this fixture tend to be high/low scoring? Who dominates?
6. Scoreline: use implied goals ({h_exp} vs {a_exp}) to pick a REALISTIC score.

Return ONLY this JSON:
{{
  "winner": "EXACTLY {home_name} OR {away_name} OR Draw",
  "score": "realistic scoreline based on implied goals above — e.g. 1-0, 2-0, 1-1, 0-0, 3-1 etc.",
  "confidence": "High or Medium or Low",
  "btts": "Yes or No",
  "over25": "Yes or No",
  "winProbHome": 0,
  "winProbDraw": 0,
  "winProbAway": 0,
  "keyFactor": "most statistically significant factor from the data",
  "xgInsight": "one sentence on what xG reveals that raw results hide",
  "scoringPattern": "low-scoring defensive battle / open attacking game / one-sided etc.",
  "analysis": "350+ word expert analysis with specific numbers. Cover: xG comparison, PPDA/pressing, form, H2H, implied goals, regression risk. Be direct and confident.",
  "homeStrengths": ["stat-backed strength", "stat-backed strength", "stat-backed strength"],
  "awayStrengths": ["stat-backed strength", "stat-backed strength", "stat-backed strength"],
  "riskFactor": "specific data-driven reason this prediction could be wrong"
}}

RULES: winner = exact name or Draw. Probabilities sum to 100. Score must reflect ~{h_exp} vs ~{a_exp} implied goals."""

    raw = groq_chat([
        {"role": "system", "content": (
            "You are a professional football statistician and analyst. "
            "You base every prediction on xG data, form, and implied goals calculations. "
            "You never default to generic scorelines like 2-1 — you always use the data. "
            "You return only valid JSON with no extra text."
        )},
        {"role": "user", "content": prompt}
    ], temperature=0.4, max_tokens=2000)

    result = extract_json(raw)

    valid = [home_name, away_name, "Draw"]
    if result.get("winner") not in valid:
        ph = result.get("winProbHome", 0)
        pa = result.get("winProbAway", 0)
        pd = result.get("winProbDraw", 0)
        result["winner"] = home_name if ph>=pa and ph>=pd else away_name if pa>=ph and pa>=pd else "Draw"

    ph = int(result.get("winProbHome", 40))
    pd_v = int(result.get("winProbDraw", 25))
    pa = int(result.get("winProbAway", 35))
    total = ph + pd_v + pa
    if total != 100 and total > 0:
        result["winProbHome"]  = round(ph * 100 / total)
        result["winProbDraw"]  = round(pd_v * 100 / total)
        result["winProbAway"]  = 100 - result["winProbHome"] - result["winProbDraw"]

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

        # 6. xG data from Understat (free, no key needed)
        for key, team in [("home", ht), ("away", at)]:
            xg_data = get_understat_team_xg(team.get("name",""), league_code)
            result[f"{key}XG"] = xg_data
            if xg_data:
                print(f"[understat] {team['name']}: xG/g={xg_data['xG_per']} xGA/g={xg_data['xGA_per']} ppda={xg_data['ppda']}")
            else:
                print(f"[understat] no xG data for {team['name']}")

        # 7. AI prediction (Groq)
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
