import { useState, useEffect, useRef } from "react";

const LEAGUES = [
  { id: "epl", name: "Premier League", flag: "🏴󠁧󠁢󠁥󠁮󠁧󠁿", color: "#38003c" },
  { id: "la_liga", name: "La Liga", flag: "🇪🇸", color: "#ee8707" },
  { id: "bundesliga", name: "Bundesliga", flag: "🇩🇪", color: "#d4021d" },
  { id: "serie_a", name: "Serie A", flag: "🇮🇹", color: "#008fd7" },
  { id: "ligue_1", name: "Ligue 1", flag: "🇫🇷", color: "#091c3e" },
  { id: "champions_league", name: "Champions League", flag: "🌟", color: "#1a1a2e" },
  { id: "mls", name: "World Cup / Euro", flag: "🌍", color: "#006633" },
];

const ANALYSIS_SECTIONS = [
  { key: "team_form", icon: "📊", label: "Team Form & Performance" },
  { key: "head_to_head", icon: "⚔️", label: "Head-to-Head History" },
  { key: "player_analysis", icon: "👤", label: "Key Players Analysis" },
  { key: "injuries", icon: "🏥", label: "Injuries & Suspensions" },
  { key: "tactics", icon: "🎯", label: "Tactical Analysis" },
  { key: "prediction", icon: "🔮", label: "AI Final Prediction" },
];

function TypingText({ text, speed = 18, onDone }) {
  const [displayed, setDisplayed] = useState("");
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    setDisplayed("");
    setIdx(0);
  }, [text]);

  useEffect(() => {
    if (idx < text.length) {
      const t = setTimeout(() => {
        setDisplayed((p) => p + text[idx]);
        setIdx((i) => i + 1);
      }, speed);
      return () => clearTimeout(t);
    } else if (idx === text.length && onDone) {
      onDone();
    }
  }, [idx, text, speed, onDone]);

  return <span>{displayed}<span className="cursor">▋</span></span>;
}

function PredictionCard({ data }) {
  if (!data) return null;
  const { homeTeam, awayTeam, sections, prediction } = data;
  const [activeSection, setActiveSection] = useState(null);
  const [visibleSections, setVisibleSections] = useState([]);
  const [typing, setTyping] = useState(null);
  const [doneTyping, setDoneTyping] = useState(false);

  useEffect(() => {
    // Reveal sections one by one
    let i = 0;
    const interval = setInterval(() => {
      if (i < ANALYSIS_SECTIONS.length) {
        setVisibleSections((p) => [...p, ANALYSIS_SECTIONS[i].key]);
        if (i === 0) setActiveSection(ANALYSIS_SECTIONS[0].key);
        i++;
      } else {
        clearInterval(interval);
      }
    }, 400);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    if (activeSection) {
      setTyping(sections[activeSection] || "");
      setDoneTyping(false);
    }
  }, [activeSection]);

  const winProb = prediction?.winProbability || {};

  return (
    <div style={{
      background: "linear-gradient(135deg, #0a0e1a 0%, #0d1b2a 50%, #0a1628 100%)",
      border: "1px solid rgba(0,200,120,0.15)",
      borderRadius: "20px",
      overflow: "hidden",
      boxShadow: "0 0 60px rgba(0,200,120,0.05), 0 20px 60px rgba(0,0,0,0.6)",
    }}>
      {/* Match Header */}
      <div style={{
        padding: "28px 32px 20px",
        background: "linear-gradient(90deg, rgba(0,200,120,0.08) 0%, rgba(0,120,255,0.06) 100%)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16 }}>
          <div style={{ flex: 1, textAlign: "center" }}>
            <div style={{ fontSize: 48, marginBottom: 4 }}>{homeTeam.logo}</div>
            <div style={{ color: "#fff", fontFamily: "'Bebas Neue', sans-serif", fontSize: 22, letterSpacing: 2 }}>{homeTeam.name}</div>
            <div style={{ color: "#00c878", fontSize: 12, marginTop: 4 }}>Form: {homeTeam.form}</div>
          </div>
          <div style={{ textAlign: "center", padding: "0 16px" }}>
            <div style={{ color: "rgba(255,255,255,0.3)", fontSize: 11, letterSpacing: 3, marginBottom: 6 }}>VS</div>
            <div style={{
              background: "rgba(0,200,120,0.15)",
              border: "1px solid rgba(0,200,120,0.3)",
              borderRadius: 8,
              padding: "4px 12px",
              color: "#00c878",
              fontSize: 11,
              letterSpacing: 2,
            }}>{data.league}</div>
          </div>
          <div style={{ flex: 1, textAlign: "center" }}>
            <div style={{ fontSize: 48, marginBottom: 4 }}>{awayTeam.logo}</div>
            <div style={{ color: "#fff", fontFamily: "'Bebas Neue', sans-serif", fontSize: 22, letterSpacing: 2 }}>{awayTeam.name}</div>
            <div style={{ color: "#4a9eff", fontSize: 12, marginTop: 4 }}>Form: {awayTeam.form}</div>
          </div>
        </div>

        {/* Win probability bar */}
        <div style={{ marginTop: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "rgba(255,255,255,0.5)", marginBottom: 6 }}>
            <span style={{ color: "#00c878" }}>{winProb.home}% Home Win</span>
            <span style={{ color: "rgba(255,255,255,0.4)" }}>{winProb.draw}% Draw</span>
            <span style={{ color: "#4a9eff" }}>{winProb.away}% Away Win</span>
          </div>
          <div style={{ display: "flex", borderRadius: 4, overflow: "hidden", height: 8 }}>
            <div style={{ width: `${winProb.home}%`, background: "linear-gradient(90deg, #00c878, #00a862)", transition: "width 1s ease" }} />
            <div style={{ width: `${winProb.draw}%`, background: "rgba(255,255,255,0.15)" }} />
            <div style={{ width: `${winProb.away}%`, background: "linear-gradient(90deg, #2a6eff, #4a9eff)", transition: "width 1s ease" }} />
          </div>
        </div>
      </div>

      {/* Section Nav */}
      <div style={{ display: "flex", overflowX: "auto", borderBottom: "1px solid rgba(255,255,255,0.06)", padding: "0 16px" }}>
        {ANALYSIS_SECTIONS.map((s) => (
          <button
            key={s.key}
            onClick={() => visibleSections.includes(s.key) && setActiveSection(s.key)}
            style={{
              background: "none",
              border: "none",
              padding: "14px 16px",
              cursor: visibleSections.includes(s.key) ? "pointer" : "not-allowed",
              color: activeSection === s.key ? "#00c878" : visibleSections.includes(s.key) ? "rgba(255,255,255,0.6)" : "rgba(255,255,255,0.2)",
              fontSize: 12,
              fontFamily: "inherit",
              whiteSpace: "nowrap",
              borderBottom: activeSection === s.key ? "2px solid #00c878" : "2px solid transparent",
              transition: "all 0.2s",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <span>{s.icon}</span>
            {s.label}
            {!visibleSections.includes(s.key) && (
              <span style={{
                width: 6, height: 6, borderRadius: "50%",
                background: "rgba(255,255,255,0.1)",
                animation: "pulse 1s infinite",
                display: "inline-block",
              }} />
            )}
          </button>
        ))}
      </div>

      {/* Section Content */}
      <div style={{ padding: "24px 32px", minHeight: 200 }}>
        {activeSection && (
          <div style={{
            color: "rgba(255,255,255,0.85)",
            fontSize: 14,
            lineHeight: 1.8,
            fontFamily: "'DM Sans', sans-serif",
          }}>
            {activeSection === "prediction" ? (
              <div>
                <div style={{
                  background: "linear-gradient(135deg, rgba(0,200,120,0.1), rgba(0,120,255,0.08))",
                  border: "1px solid rgba(0,200,120,0.25)",
                  borderRadius: 12,
                  padding: 20,
                  marginBottom: 16,
                }}>
                  <div style={{ color: "#00c878", fontSize: 12, letterSpacing: 2, marginBottom: 8 }}>🔮 AI VERDICT</div>
                  <div style={{ color: "#fff", fontSize: 20, fontFamily: "'Bebas Neue', sans-serif", letterSpacing: 2 }}>
                    {prediction.winner} — {prediction.score}
                  </div>
                  <div style={{ color: "rgba(255,255,255,0.6)", fontSize: 13, marginTop: 8 }}>{prediction.confidence} Confidence</div>
                </div>
                <TypingText text={sections.prediction} speed={14} />
              </div>
            ) : (
              <TypingText
                key={activeSection}
                text={sections[activeSection] || ""}
                speed={12}
                onDone={() => setDoneTyping(true)}
              />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function LoadingOrb() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "40px 0" }}>
      <div style={{
        width: 64, height: 64, borderRadius: "50%",
        border: "2px solid rgba(0,200,120,0.15)",
        borderTop: "2px solid #00c878",
        animation: "spin 1s linear infinite",
        marginBottom: 20,
      }} />
      <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 13, letterSpacing: 2 }}>ANALYZING MATCH DATA...</div>
      <div style={{ color: "rgba(0,200,120,0.5)", fontSize: 11, marginTop: 6, letterSpacing: 1 }}>
        Scanning 10+ years of statistics
      </div>
    </div>
  );
}

export default function FootballBot() {
  const [homeTeam, setHomeTeam] = useState("");
  const [awayTeam, setAwayTeam] = useState("");
  const [league, setLeague] = useState("epl");
  const [matchDate, setMatchDate] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const chatEndRef = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatMessages]);

  const analyzeMatch = async () => {
    if (!homeTeam.trim() || !awayTeam.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);

    const selectedLeague = LEAGUES.find(l => l.id === league);

    const prompt = `You are an elite football analytics AI with deep knowledge of all top European leagues, World Cup, and European Championship. Analyze this match thoroughly:

HOME TEAM: ${homeTeam}
AWAY TEAM: ${awayTeam}
COMPETITION: ${selectedLeague?.name}
DATE: ${matchDate || "upcoming fixture"}

Provide a full professional football analytics report in JSON format with EXACTLY this structure (no markdown, pure JSON):
{
  "homeTeam": {
    "name": "${homeTeam}",
    "logo": "(relevant emoji flag or ball)",
    "form": "(last 5 results e.g. W-W-D-L-W)",
    "avgGoalsScored": "(number)",
    "avgGoalsConceded": "(number)",
    "cleanSheets": "(last 10 games)",
    "rankInLeague": "(current position)"
  },
  "awayTeam": {
    "name": "${awayTeam}",
    "logo": "(relevant emoji)",
    "form": "(last 5 results)",
    "avgGoalsScored": "(number)",
    "avgGoalsConceded": "(number)",
    "cleanSheets": "(last 10 games)",
    "rankInLeague": "(current position)"
  },
  "league": "${selectedLeague?.name}",
  "sections": {
    "team_form": "(Write 180-220 words: Detailed analysis of both teams' recent form, momentum, home/away records, goals scored/conceded trends, any winning/losing streaks, how they perform under pressure)",
    "head_to_head": "(Write 180-220 words: Last 5-8 head-to-head encounters, scores, patterns, which team dominates historically, notable performances, venue tendencies, psychological edge)",
    "player_analysis": "(Write 200-240 words: Key players for both teams — top scorers, playmakers, defenders. Analyze their season stats, recent form, match impact potential, who is in form vs struggling)",
    "injuries": "(Write 150-180 words: Known or likely injuries and suspensions for both squads, how absences affect team strength, who might be doubtful, the impact on tactical setup)",
    "tactics": "(Write 180-220 words: Expected formations, tactical approaches, how each manager sets up, pressing style, set piece threats, tactical matchups and potential key battles on the pitch)",
    "prediction": "(Write 200-250 words: Comprehensive final prediction reasoning — explain exactly WHY you predict this outcome, weighting all factors: form, H2H, squad depth, tactical edge, injuries, motivation, home advantage. Be confident and decisive.)"
  },
  "prediction": {
    "winner": "(team name or 'Draw')",
    "score": "(predicted scoreline e.g. 2-1)",
    "confidence": "(High / Medium / Low)",
    "btts": "(Yes/No - both teams to score)",
    "over25": "(Yes/No - over 2.5 goals)",
    "keyFactor": "(one sentence: the single most decisive factor)"
  },
  "winProbability": {
    "home": (integer 0-100),
    "draw": (integer 0-100),
    "away": (integer 0-100)
  }
}

Use your deep football knowledge. Make it realistic and data-driven. Probabilities must sum to 100.`;

    try {
      const response = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-20250514",
          max_tokens: 2500,
          system: "You are a world-class football analytics expert. Always respond with valid JSON only, no markdown fences, no preamble.",
          messages: [{ role: "user", content: prompt }],
        }),
      });

      const data = await response.json();
      const text = data.content?.map(c => c.text || "").join("") || "";
      const clean = text.replace(/```json|```/g, "").trim();
      const parsed = JSON.parse(clean);

      setResult({
        homeTeam: parsed.homeTeam,
        awayTeam: parsed.awayTeam,
        league: parsed.league,
        sections: parsed.sections,
        prediction: { ...parsed.prediction, winProbability: parsed.winProbability },
      });

      setChatMessages([{
        role: "assistant",
        text: `✅ Analysis complete for **${homeTeam} vs ${awayTeam}**! I've broken down team form, head-to-head history, key players, injuries, tactics, and given my final prediction. Ask me anything about this match!`,
      }]);
    } catch (e) {
      setError("Failed to analyze match. Please check team names and try again.");
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  const sendChat = async () => {
    if (!chatInput.trim() || chatLoading || !result) return;
    const userMsg = chatInput.trim();
    setChatInput("");
    setChatMessages(p => [...p, { role: "user", text: userMsg }]);
    setChatLoading(true);

    const context = `Match: ${result.homeTeam.name} vs ${result.awayTeam.name} (${result.league})
Home form: ${result.homeTeam.form}, Away form: ${result.awayTeam.form}
AI Prediction: ${result.prediction.winner} ${result.prediction.score} (${result.prediction.confidence} confidence)
Win probabilities: Home ${result.prediction.winProbability?.home}%, Draw ${result.prediction.winProbability?.draw}%, Away ${result.prediction.winProbability?.away}%
Key factor: ${result.prediction.keyFactor}`;

    try {
      const response = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "claude-sonnet-4-20250514",
          max_tokens: 500,
          system: `You are a football analytics expert who just analyzed a match. Context: ${context}. Answer questions about this match analytically, confidently, and concisely. Use football expertise.`,
          messages: [...chatMessages.map(m => ({ role: m.role === "assistant" ? "assistant" : "user", content: m.text })), { role: "user", content: userMsg }],
        }),
      });
      const data = await response.json();
      const reply = data.content?.map(c => c.text || "").join("") || "I couldn't process that question.";
      setChatMessages(p => [...p, { role: "assistant", text: reply }]);
    } catch {
      setChatMessages(p => [...p, { role: "assistant", text: "Something went wrong. Try again." }]);
    } finally {
      setChatLoading(false);
    }
  };

  const selectedLeague = LEAGUES.find(l => l.id === league);

  return (
    <div style={{
      minHeight: "100vh",
      background: "#060a12",
      fontFamily: "'DM Sans', 'Segoe UI', sans-serif",
      color: "#fff",
      padding: "0",
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Bebas+Neue&family=DM+Sans:wght@300;400;500;600&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: rgba(255,255,255,0.03); }
        ::-webkit-scrollbar-thumb { background: rgba(0,200,120,0.3); border-radius: 2px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes pulse { 0%,100% { opacity:0.3; } 50% { opacity:1; } }
        @keyframes fadeInUp { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
        @keyframes glow { 0%,100% { box-shadow:0 0 20px rgba(0,200,120,0.1); } 50% { box-shadow:0 0 40px rgba(0,200,120,0.2); } }
        .cursor { animation: pulse 1s infinite; margin-left: 2px; color: #00c878; }
        .league-btn:hover { border-color: rgba(0,200,120,0.4) !important; background: rgba(0,200,120,0.08) !important; }
        .analyze-btn:hover { transform: translateY(-1px); box-shadow: 0 8px 32px rgba(0,200,120,0.3) !important; }
        .analyze-btn:active { transform: translateY(0); }
        input::placeholder { color: rgba(255,255,255,0.25) !important; }
        input:focus { outline: none; border-color: rgba(0,200,120,0.5) !important; }
        textarea:focus { outline: none; }
      `}</style>

      {/* Header */}
      <div style={{
        padding: "28px 40px 24px",
        borderBottom: "1px solid rgba(255,255,255,0.05)",
        background: "linear-gradient(180deg, rgba(0,200,120,0.04) 0%, transparent 100%)",
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}>
        <div style={{
          width: 44, height: 44, borderRadius: 12,
          background: "linear-gradient(135deg, #00c878, #00a060)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 22,
          boxShadow: "0 4px 16px rgba(0,200,120,0.3)",
          animation: "glow 3s ease-in-out infinite",
        }}>⚽</div>
        <div>
          <div style={{ fontFamily: "'Bebas Neue', sans-serif", fontSize: 26, letterSpacing: 3, color: "#fff" }}>
            SCOUT<span style={{ color: "#00c878" }}>AI</span>
          </div>
          <div style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", letterSpacing: 2 }}>
            FOOTBALL INTELLIGENCE ENGINE
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          {["EPL", "LaLiga", "Serie A", "BL", "L1", "UCL"].map(t => (
            <span key={t} style={{
              padding: "4px 8px",
              background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.08)",
              borderRadius: 4,
              fontSize: 10,
              color: "rgba(255,255,255,0.3)",
              letterSpacing: 1,
            }}>{t}</span>
          ))}
        </div>
      </div>

      <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 24px" }}>

        {/* Match Input Panel */}
        <div style={{
          background: "rgba(255,255,255,0.02)",
          border: "1px solid rgba(255,255,255,0.07)",
          borderRadius: 16,
          padding: 28,
          marginBottom: 28,
          animation: "fadeInUp 0.5s ease",
        }}>
          <div style={{ color: "rgba(255,255,255,0.5)", fontSize: 11, letterSpacing: 3, marginBottom: 20 }}>
            📋 MATCH SETUP
          </div>

          {/* League Selector */}
          <div style={{ marginBottom: 20 }}>
            <div style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", letterSpacing: 2, marginBottom: 10 }}>COMPETITION</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {LEAGUES.map(l => (
                <button
                  key={l.id}
                  className="league-btn"
                  onClick={() => setLeague(l.id)}
                  style={{
                    background: league === l.id ? "rgba(0,200,120,0.12)" : "rgba(255,255,255,0.03)",
                    border: `1px solid ${league === l.id ? "rgba(0,200,120,0.4)" : "rgba(255,255,255,0.08)"}`,
                    borderRadius: 8,
                    padding: "7px 14px",
                    color: league === l.id ? "#00c878" : "rgba(255,255,255,0.5)",
                    fontSize: 12,
                    cursor: "pointer",
                    fontFamily: "inherit",
                    transition: "all 0.2s",
                    display: "flex", alignItems: "center", gap: 6,
                  }}
                >
                  <span>{l.flag}</span> {l.name}
                </button>
              ))}
            </div>
          </div>

          {/* Team Inputs */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 12, alignItems: "center", marginBottom: 16 }}>
            <div>
              <div style={{ fontSize: 11, color: "rgba(0,200,120,0.6)", letterSpacing: 2, marginBottom: 8 }}>HOME TEAM</div>
              <input
                value={homeTeam}
                onChange={e => setHomeTeam(e.target.value)}
                placeholder="e.g. Manchester City"
                onKeyDown={e => e.key === "Enter" && analyzeMatch()}
                style={{
                  width: "100%",
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 10,
                  padding: "12px 16px",
                  color: "#fff",
                  fontSize: 14,
                  fontFamily: "inherit",
                  transition: "border-color 0.2s",
                }}
              />
            </div>
            <div style={{
              width: 36, height: 36, borderRadius: "50%",
              background: "rgba(255,255,255,0.05)",
              display: "flex", alignItems: "center", justifyContent: "center",
              color: "rgba(255,255,255,0.3)", fontSize: 12, fontFamily: "Bebas Neue",
              letterSpacing: 1, marginTop: 22,
            }}>VS</div>
            <div>
              <div style={{ fontSize: 11, color: "rgba(74,158,255,0.6)", letterSpacing: 2, marginBottom: 8 }}>AWAY TEAM</div>
              <input
                value={awayTeam}
                onChange={e => setAwayTeam(e.target.value)}
                placeholder="e.g. Arsenal"
                onKeyDown={e => e.key === "Enter" && analyzeMatch()}
                style={{
                  width: "100%",
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 10,
                  padding: "12px 16px",
                  color: "#fff",
                  fontSize: 14,
                  fontFamily: "inherit",
                  transition: "border-color 0.2s",
                }}
              />
            </div>
          </div>

          <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 11, color: "rgba(255,255,255,0.35)", letterSpacing: 2, marginBottom: 8 }}>MATCH DATE (optional)</div>
              <input
                type="date"
                value={matchDate}
                onChange={e => setMatchDate(e.target.value)}
                style={{
                  width: "100%",
                  background: "rgba(255,255,255,0.04)",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 10,
                  padding: "12px 16px",
                  color: "rgba(255,255,255,0.6)",
                  fontSize: 14,
                  fontFamily: "inherit",
                  colorScheme: "dark",
                }}
              />
            </div>
            <button
              className="analyze-btn"
              onClick={analyzeMatch}
              disabled={loading || !homeTeam.trim() || !awayTeam.trim()}
              style={{
                marginTop: 24,
                padding: "13px 32px",
                background: loading || !homeTeam.trim() || !awayTeam.trim()
                  ? "rgba(0,200,120,0.2)"
                  : "linear-gradient(135deg, #00c878, #00a060)",
                border: "none",
                borderRadius: 10,
                color: loading || !homeTeam.trim() || !awayTeam.trim() ? "rgba(255,255,255,0.4)" : "#000",
                fontSize: 13,
                fontWeight: 600,
                fontFamily: "inherit",
                cursor: loading || !homeTeam.trim() || !awayTeam.trim() ? "not-allowed" : "pointer",
                letterSpacing: 1,
                transition: "all 0.2s",
                whiteSpace: "nowrap",
                boxShadow: "0 4px 16px rgba(0,200,120,0.15)",
              }}
            >
              {loading ? "⚡ Analyzing..." : "🔍 Analyze Match"}
            </button>
          </div>
        </div>

        {/* Error */}
        {error && (
          <div style={{
            background: "rgba(255,60,60,0.1)",
            border: "1px solid rgba(255,60,60,0.2)",
            borderRadius: 10,
            padding: "14px 20px",
            color: "#ff6060",
            marginBottom: 24,
            fontSize: 13,
          }}>{error}</div>
        )}

        {/* Loading */}
        {loading && <LoadingOrb />}

        {/* Result */}
        {result && !loading && (
          <div style={{ animation: "fadeInUp 0.6s ease" }}>
            <PredictionCard data={result} />

            {/* Stat Pills */}
            <div style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 12,
              marginTop: 20,
              marginBottom: 24,
            }}>
              {[
                { label: "Predicted Score", value: result.prediction.score, color: "#00c878" },
                { label: "BTTS", value: result.prediction.btts, color: result.prediction.btts === "Yes" ? "#ffd700" : "#666" },
                { label: "Over 2.5 Goals", value: result.prediction.over25, color: result.prediction.over25 === "Yes" ? "#ffd700" : "#666" },
                { label: "Confidence", value: result.prediction.confidence, color: result.prediction.confidence === "High" ? "#00c878" : result.prediction.confidence === "Medium" ? "#ffd700" : "#ff6060" },
              ].map(s => (
                <div key={s.label} style={{
                  background: "rgba(255,255,255,0.02)",
                  border: "1px solid rgba(255,255,255,0.07)",
                  borderRadius: 12,
                  padding: "14px 16px",
                  textAlign: "center",
                }}>
                  <div style={{ color: "rgba(255,255,255,0.4)", fontSize: 10, letterSpacing: 2, marginBottom: 6 }}>{s.label.toUpperCase()}</div>
                  <div style={{ color: s.color, fontFamily: "'Bebas Neue', sans-serif", fontSize: 20, letterSpacing: 2 }}>{s.value}</div>
                </div>
              ))}
            </div>

            {/* Key Factor */}
            <div style={{
              background: "rgba(0,200,120,0.05)",
              border: "1px solid rgba(0,200,120,0.15)",
              borderRadius: 10,
              padding: "14px 20px",
              marginBottom: 28,
              display: "flex",
              gap: 12,
              alignItems: "flex-start",
            }}>
              <span style={{ fontSize: 18 }}>🔑</span>
              <div>
                <div style={{ color: "#00c878", fontSize: 10, letterSpacing: 2, marginBottom: 4 }}>KEY DECISIVE FACTOR</div>
                <div style={{ color: "rgba(255,255,255,0.75)", fontSize: 13 }}>{result.prediction.keyFactor}</div>
              </div>
            </div>

            {/* Chat */}
            <div style={{
              background: "rgba(255,255,255,0.02)",
              border: "1px solid rgba(255,255,255,0.07)",
              borderRadius: 16,
              overflow: "hidden",
            }}>
              <div style={{
                padding: "14px 20px",
                borderBottom: "1px solid rgba(255,255,255,0.05)",
                display: "flex",
                alignItems: "center",
                gap: 10,
                color: "rgba(255,255,255,0.5)",
                fontSize: 11,
                letterSpacing: 2,
              }}>
                <span>💬</span> ASK SCOUT AI ABOUT THIS MATCH
              </div>
              <div style={{ maxHeight: 240, overflowY: "auto", padding: "16px 20px", display: "flex", flexDirection: "column", gap: 12 }}>
                {chatMessages.map((m, i) => (
                  <div key={i} style={{
                    display: "flex",
                    justifyContent: m.role === "user" ? "flex-end" : "flex-start",
                    animation: "fadeInUp 0.3s ease",
                  }}>
                    <div style={{
                      maxWidth: "80%",
                      padding: "10px 14px",
                      borderRadius: m.role === "user" ? "12px 12px 4px 12px" : "12px 12px 12px 4px",
                      background: m.role === "user" ? "rgba(0,200,120,0.15)" : "rgba(255,255,255,0.04)",
                      border: `1px solid ${m.role === "user" ? "rgba(0,200,120,0.2)" : "rgba(255,255,255,0.07)"}`,
                      color: m.role === "user" ? "#00c878" : "rgba(255,255,255,0.75)",
                      fontSize: 13,
                      lineHeight: 1.6,
                    }}>
                      {m.text}
                    </div>
                  </div>
                ))}
                {chatLoading && (
                  <div style={{ display: "flex", gap: 4, padding: "8px 0" }}>
                    {[0, 1, 2].map(i => (
                      <div key={i} style={{
                        width: 6, height: 6, borderRadius: "50%",
                        background: "#00c878",
                        animation: `pulse 1s infinite ${i * 0.15}s`,
                      }} />
                    ))}
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>
              <div style={{
                padding: "12px 16px",
                borderTop: "1px solid rgba(255,255,255,0.05)",
                display: "flex",
                gap: 8,
              }}>
                <input
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && sendChat()}
                  placeholder="Ask about tactics, players, betting angles..."
                  style={{
                    flex: 1,
                    background: "rgba(255,255,255,0.04)",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 8,
                    padding: "10px 14px",
                    color: "#fff",
                    fontSize: 13,
                    fontFamily: "inherit",
                    outline: "none",
                  }}
                />
                <button
                  onClick={sendChat}
                  disabled={chatLoading || !chatInput.trim()}
                  style={{
                    padding: "10px 18px",
                    background: chatLoading || !chatInput.trim() ? "rgba(0,200,120,0.15)" : "rgba(0,200,120,0.2)",
                    border: "1px solid rgba(0,200,120,0.3)",
                    borderRadius: 8,
                    color: "#00c878",
                    cursor: "pointer",
                    fontSize: 16,
                    fontFamily: "inherit",
                  }}
                >↑</button>
              </div>
            </div>
          </div>
        )}

        {/* Empty state */}
        {!result && !loading && (
          <div style={{ textAlign: "center", padding: "48px 0", color: "rgba(255,255,255,0.2)" }}>
            <div style={{ fontSize: 56, marginBottom: 16, filter: "grayscale(0.5)" }}>⚽</div>
            <div style={{ fontFamily: "'Bebas Neue', sans-serif", fontSize: 20, letterSpacing: 3, marginBottom: 8 }}>
              ENTER A MATCH TO ANALYZE
            </div>
            <div style={{ fontSize: 12, letterSpacing: 1, lineHeight: 1.8, maxWidth: 360, margin: "0 auto" }}>
              Team form · Head-to-head · Player stats · Injuries<br />
              Tactical breakdown · AI prediction & confidence
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
