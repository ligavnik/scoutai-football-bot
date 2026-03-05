# ⚽ ScoutAI — Football Analytics & Prediction Bot

> Real match data + AI predictions. 100% free, runs in the browser — no terminal needed.

**Live demo:** `https://yourapp.railway.app` (after deploying)

---

## Features

- 📅 **Upcoming Fixtures** — click any match for instant AI prediction
- 📊 **Standings · Form · H2H · Squad**
- 🔮 **AI Prediction** — winner, scoreline, BTTS, Over 2.5, win %
- 💬 **Chat** — ask follow-up questions about the match

---

## Two free API keys needed (no credit card)

| Key | Where to get |
|-----|-------------|
| Football data | [football-data.org/client/register](https://www.football-data.org/client/register) |
| AI (Groq) | [console.groq.com](https://console.groq.com) → API Keys → Create |

Enter both keys directly in the app — they're saved in your browser.

---

## Deploy to Railway (free hosting)

1. Fork this repo on GitHub
2. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
3. Select your fork
4. Done — Railway gives you a public URL like `https://yourapp.railway.app`

That's it. Share the URL with anyone — no setup needed on their end.

---

## Run locally

```bash
pip install -r requirements.txt
python server.py
# open http://localhost:5000
```

---

## Tech stack

- **Backend:** Python / Flask
- **AI:** Groq API (llama-3.1-8b-instant) — free tier
- **Football data:** football-data.org — free tier
- **Hosting:** Railway.app — free tier
