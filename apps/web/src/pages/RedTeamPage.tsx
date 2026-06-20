"use client";

import { useState, useEffect, useCallback, useRef } from "react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Scenario {
  id: string;
  name: string;
  description: string;
  hint: string;
  expected_block: string;
}

interface GuardrailHit {
  guardrail: string;
  passed: boolean;
  detail: string;
}

interface AttackResult {
  attack_id: string;
  scenario_name: string;
  team_name: string;
  outcome: string;
  depth_reached: number;
  points_earned: number;
  guardrail_trail: GuardrailHit[];
  verdict: string;
  timestamp: string;
}

interface LeaderboardEntry {
  team_name: string;
  total_points: number;
  attacks_attempted: number;
  deepest_penetration: number;
  timestamp: string;
}

// ── Constants ─────────────────────────────────────────────────────────────────

const API_BASE = "http://localhost:8000";

const OUTCOME_COLORS: Record<string, string> = {
  blocked: "#c0392b",
  escalated: "#d1671f",
  settled: "#27ae60",
};

const OUTCOME_LABELS: Record<string, string> = {
  blocked: "BLOCKED",
  escalated: "ESCALATED",
  settled: "🏆 VAULT BROKEN",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function PulsingDot({ color }: { color: string }) {
  return (
    <span
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        backgroundColor: color,
        boxShadow: `0 0 6px ${color}`,
        animation: "pulse 1.4s ease-in-out infinite",
        flexShrink: 0,
      }}
    />
  );
}

function GuardrailTrail({ trail }: { trail: GuardrailHit[] }) {
  return (
    <div style={{ marginTop: 10 }}>
      <div
        style={{
          fontSize: 11,
          color: "var(--muted)",
          textTransform: "uppercase",
          letterSpacing: "0.08em",
          marginBottom: 6,
          fontWeight: 600,
        }}
      >
        Guardrail Trail
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 4,
          maxHeight: 160,
          overflowY: "auto",
        }}
      >
        {trail.map((hit, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "flex-start",
              gap: 6,
              fontFamily: "monospace",
              fontSize: 11,
              lineHeight: 1.4,
              padding: "4px 6px",
              borderRadius: 4,
              background: "rgba(255,255,255,0.03)",
            }}
          >
            <span
              style={{
                color: hit.passed ? "#2ecc71" : "#c0392b",
                fontWeight: 700,
                flexShrink: 0,
                marginTop: 1,
              }}
            >
              {hit.passed ? "[PASS]" : "[STOP]"}
            </span>
            <span style={{ color: "var(--text)", flexShrink: 0, fontWeight: 600 }}>
              {hit.guardrail}
            </span>
            <span style={{ color: "var(--muted)", wordBreak: "break-word" }}>
              — {hit.detail.length > 60 ? hit.detail.slice(0, 60) + "…" : hit.detail}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ScenarioCard({
  scenario,
  teamName,
  isRunning,
  onAttack,
  result,
}: {
  scenario: Scenario;
  teamName: string;
  isRunning: boolean;
  onAttack: (id: string) => void;
  result: AttackResult | null;
}) {
  const [hintOpen, setHintOpen] = useState(false);
  const attacking = isRunning;
  const outcomeColor = result ? OUTCOME_COLORS[result.outcome] ?? "#959190" : null;

  return (
    <div
      style={{
        background: "var(--surface)",
        border: attacking
          ? "1px solid var(--accent-strong)"
          : "1px solid var(--border)",
        borderRadius: 12,
        padding: "20px 22px",
        display: "flex",
        flexDirection: "column",
        gap: 12,
        position: "relative",
        transition: "border-color 0.3s ease",
        boxShadow: attacking
          ? "0 0 20px rgba(239,124,36,0.25), 0 0 40px rgba(239,124,36,0.1)"
          : "0 2px 8px rgba(0,0,0,0.4)",
        animation: attacking ? "cardPulse 1.4s ease-in-out infinite" : "none",
      }}
    >
      {/* Badge + Name */}
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <span
          style={{
            background: "rgba(209,103,31,0.15)",
            border: "1px solid rgba(209,103,31,0.4)",
            color: "var(--accent-strong)",
            borderRadius: 6,
            padding: "2px 8px",
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.05em",
            flexShrink: 0,
          }}
        >
          {scenario.id}
        </span>
        <span style={{ fontWeight: 700, fontSize: 15, color: "var(--text)", lineHeight: 1.3 }}>
          {scenario.name}
        </span>
      </div>

      {/* Description */}
      <p style={{ margin: 0, fontSize: 13, color: "var(--muted)", lineHeight: 1.55 }}>
        {scenario.description}
      </p>

      {/* Hint collapsible */}
      <div>
        <button
          onClick={() => setHintOpen((v) => !v)}
          style={{
            background: "none",
            border: "none",
            cursor: "pointer",
            color: "var(--accent)",
            fontSize: 12,
            fontWeight: 600,
            padding: 0,
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          <span style={{ transition: "transform 0.2s", display: "inline-block", transform: hintOpen ? "rotate(90deg)" : "none" }}>
            ▸
          </span>
          HINT
        </button>
        {hintOpen && (
          <div
            style={{
              marginTop: 8,
              padding: "10px 12px",
              background: "var(--surface-soft)",
              borderRadius: 8,
              fontSize: 12,
              color: "var(--muted)",
              fontStyle: "italic",
              lineHeight: 1.5,
              borderLeft: "3px solid var(--accent)",
            }}
          >
            {scenario.hint}
          </div>
        )}
      </div>

      {/* Attack button / status */}
      {attacking ? (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "10px 14px",
            background: "rgba(239,124,36,0.08)",
            borderRadius: 8,
            border: "1px solid rgba(239,124,36,0.3)",
          }}
        >
          <PulsingDot color="var(--accent-strong)" />
          <span style={{ fontSize: 13, color: "var(--accent-strong)", fontWeight: 600 }}>
            Attacking…
          </span>
        </div>
      ) : (
        <button
          onClick={() => onAttack(scenario.id)}
          disabled={!teamName || isRunning}
          style={{
            padding: "10px 18px",
            borderRadius: 8,
            border: "1px solid var(--accent)",
            background: teamName && !isRunning ? "rgba(209,103,31,0.15)" : "rgba(255,255,255,0.03)",
            color: teamName && !isRunning ? "var(--accent-strong)" : "var(--muted)",
            fontWeight: 700,
            fontSize: 13,
            cursor: teamName && !isRunning ? "pointer" : "not-allowed",
            letterSpacing: "0.04em",
            transition: "all 0.2s ease",
          }}
          onMouseEnter={(e) => {
            if (teamName && !isRunning) {
              (e.target as HTMLButtonElement).style.background = "rgba(209,103,31,0.28)";
            }
          }}
          onMouseLeave={(e) => {
            if (teamName && !isRunning) {
              (e.target as HTMLButtonElement).style.background = "rgba(209,103,31,0.15)";
            }
          }}
        >
          {!teamName ? "Join a team first" : "Launch Attack"}
        </button>
      )}

      {/* Result */}
      {result && !attacking && (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {/* Outcome badge + points */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
            <span
              style={{
                background: `${outcomeColor}22`,
                border: `1px solid ${outcomeColor}66`,
                color: outcomeColor!,
                borderRadius: 6,
                padding: "4px 10px",
                fontSize: 12,
                fontWeight: 700,
                letterSpacing: "0.06em",
              }}
            >
              {OUTCOME_LABELS[result.outcome] ?? result.outcome.toUpperCase()}
            </span>
            <span
              style={{
                fontSize: 13,
                color: "var(--muted)",
                fontWeight: 600,
              }}
            >
              +{result.points_earned} pts
            </span>
            <span
              style={{
                fontSize: 12,
                color: "var(--muted)",
                marginLeft: "auto",
              }}
            >
              Depth: {result.depth_reached}/4
            </span>
          </div>

          {/* Guardrail trail */}
          {result.guardrail_trail && result.guardrail_trail.length > 0 && (
            <GuardrailTrail trail={result.guardrail_trail} />
          )}

          {/* Verdict */}
          {result.verdict && (
            <p
              style={{
                margin: 0,
                fontSize: 12,
                color: "var(--muted)",
                fontStyle: "italic",
                lineHeight: 1.5,
                paddingTop: 6,
                borderTop: "1px solid var(--border)",
              }}
            >
              "{result.verdict}"
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function RedTeamPage() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenariosLoading, setScenariosLoading] = useState(true);
  const [scenariosError, setScenarioError] = useState<string | null>(null);

  const [teamName, setTeamName] = useState("");
  const [teamInput, setTeamInput] = useState("");

  const [runningAttack, setRunningAttack] = useState<string | null>(null); // scenario id
  const [results, setResults] = useState<Record<string, AttackResult>>({});
  const [attackError, setAttackError] = useState<string | null>(null);

  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [lbLoading, setLbLoading] = useState(true);
  const [lbError, setLbError] = useState<string | null>(null);
  const [resetting, setResetting] = useState(false);

  const lbIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Fetch scenarios ──────────────────────────────────────────────────────

  useEffect(() => {
    setScenariosLoading(true);
    setScenarioError(null);
    fetch(`${API_BASE}/redteam/scenarios`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setScenarios(data.scenarios ?? []);
        setScenariosLoading(false);
      })
      .catch((e) => {
        setScenarioError(e.message);
        setScenariosLoading(false);
      });
  }, []);

  // ── Fetch leaderboard ────────────────────────────────────────────────────

  const fetchLeaderboard = useCallback(() => {
    fetch(`${API_BASE}/redteam/leaderboard`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((data) => {
        setLeaderboard(Array.isArray(data) ? data : []);
        setLbLoading(false);
        setLbError(null);
      })
      .catch((e) => {
        setLbError(e.message);
        setLbLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchLeaderboard();
    lbIntervalRef.current = setInterval(fetchLeaderboard, 10_000);
    return () => {
      if (lbIntervalRef.current) clearInterval(lbIntervalRef.current);
    };
  }, [fetchLeaderboard]);

  // ── Attack ───────────────────────────────────────────────────────────────

  const handleAttack = useCallback(
    async (scenarioId: string) => {
      if (!teamName || runningAttack) return;
      setRunningAttack(scenarioId);
      setAttackError(null);
      try {
        const res = await fetch(`${API_BASE}/redteam/attack`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attack_id: scenarioId, team_name: teamName }),
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(`HTTP ${res.status}: ${text}`);
        }
        const data: AttackResult = await res.json();
        setResults((prev) => ({ ...prev, [scenarioId]: data }));
        fetchLeaderboard();
      } catch (e: unknown) {
        setAttackError(e instanceof Error ? e.message : String(e));
      } finally {
        setRunningAttack(null);
      }
    },
    [teamName, runningAttack, fetchLeaderboard]
  );

  // ── Reset leaderboard ────────────────────────────────────────────────────

  const handleReset = useCallback(async () => {
    if (resetting) return;
    if (!confirm("Reset the leaderboard? This will clear all scores.")) return;
    setResetting(true);
    try {
      await fetch(`${API_BASE}/redteam/leaderboard/reset`, { method: "POST" });
      fetchLeaderboard();
    } catch {
      // silent
    } finally {
      setResetting(false);
    }
  }, [resetting, fetchLeaderboard]);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <>
      {/* Global keyframes injected inline */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.85); }
        }
        @keyframes cardPulse {
          0%, 100% { box-shadow: 0 0 20px rgba(239,124,36,0.25), 0 0 40px rgba(239,124,36,0.1); }
          50% { box-shadow: 0 0 32px rgba(239,124,36,0.5), 0 0 60px rgba(239,124,36,0.2); }
        }
        @keyframes headerGlow {
          0%, 100% { text-shadow: 0 0 20px rgba(239,124,36,0.4); }
          50% { text-shadow: 0 0 40px rgba(239,124,36,0.8), 0 0 80px rgba(239,124,36,0.3); }
        }
        @keyframes redPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
      `}</style>

      <div
        style={{
          minHeight: "100vh",
          background: "var(--bg)",
          color: "var(--text)",
          fontFamily: "Inter, system-ui, sans-serif",
          padding: "0 0 80px",
        }}
      >
        {/* ── Header ──────────────────────────────────────────────────────── */}
        <div
          style={{
            borderBottom: "1px solid var(--border)",
            padding: "40px 48px 32px",
            background:
              "linear-gradient(180deg, rgba(192,57,43,0.06) 0%, rgba(1,0,0,0) 100%)",
          }}
        >
          <div style={{ maxWidth: 1100, margin: "0 auto" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 12 }}>
              <span
                style={{
                  fontSize: 28,
                  animation: "redPulse 1.2s ease-in-out infinite",
                  display: "inline-block",
                }}
              >
                🔴
              </span>
              <h1
                style={{
                  margin: 0,
                  fontSize: 32,
                  fontWeight: 800,
                  letterSpacing: "-0.02em",
                  color: "var(--text)",
                  animation: "headerGlow 3s ease-in-out infinite",
                }}
              >
                Break the Vault
              </h1>
            </div>
            <p
              style={{
                margin: 0,
                fontSize: 15,
                color: "var(--muted)",
                maxWidth: 560,
                lineHeight: 1.6,
              }}
            >
              Attack the treasury guardrails. Can you move money past the system?
            </p>

            {/* Scoring legend */}
            <div
              style={{
                marginTop: 20,
                display: "flex",
                gap: 20,
                flexWrap: "wrap",
              }}
            >
              {[
                { label: "0 pts", desc: "Blocked", color: "#c0392b" },
                { label: "2 pts", desc: "Escalated → Firefly", color: "#d1671f" },
                { label: "10 pts", desc: "Vault Broken 🏆", color: "#27ae60" },
              ].map(({ label, desc, color }) => (
                <div
                  key={label}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    fontSize: 12,
                  }}
                >
                  <span
                    style={{
                      background: `${color}22`,
                      border: `1px solid ${color}55`,
                      color,
                      borderRadius: 4,
                      padding: "2px 7px",
                      fontWeight: 700,
                    }}
                  >
                    {label}
                  </span>
                  <span style={{ color: "var(--muted)" }}>{desc}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div style={{ maxWidth: 1100, margin: "0 auto", padding: "0 48px" }}>
          {/* ── Team join ─────────────────────────────────────────────────── */}
          <div
            style={{
              marginTop: 32,
              padding: "20px 24px",
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 12,
              display: "flex",
              alignItems: "center",
              gap: 16,
              flexWrap: "wrap",
            }}
          >
            <span style={{ fontSize: 13, color: "var(--muted)", fontWeight: 600 }}>
              TEAM
            </span>

            {teamName ? (
              <>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                  }}
                >
                  <PulsingDot color="#27ae60" />
                  <span
                    style={{
                      background: "rgba(39,174,96,0.12)",
                      border: "1px solid rgba(39,174,96,0.35)",
                      color: "#2ecc71",
                      borderRadius: 8,
                      padding: "5px 14px",
                      fontWeight: 700,
                      fontSize: 14,
                    }}
                  >
                    {teamName}
                  </span>
                </div>
                <button
                  onClick={() => {
                    setTeamName("");
                    setTeamInput("");
                  }}
                  style={{
                    background: "none",
                    border: "1px solid var(--border)",
                    color: "var(--muted)",
                    borderRadius: 8,
                    padding: "5px 14px",
                    cursor: "pointer",
                    fontSize: 13,
                  }}
                >
                  Leave
                </button>
                <span style={{ fontSize: 13, color: "var(--muted)", marginLeft: "auto" }}>
                  Ready to attack. Select a scenario below.
                </span>
              </>
            ) : (
              <>
                <input
                  type="text"
                  value={teamInput}
                  onChange={(e) => setTeamInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && teamInput.trim()) setTeamName(teamInput.trim());
                  }}
                  placeholder="Enter your team name…"
                  style={{
                    flex: 1,
                    minWidth: 200,
                    maxWidth: 320,
                    background: "var(--surface-soft)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    padding: "9px 14px",
                    color: "var(--text)",
                    fontSize: 14,
                    outline: "none",
                  }}
                />
                <button
                  onClick={() => {
                    if (teamInput.trim()) setTeamName(teamInput.trim());
                  }}
                  disabled={!teamInput.trim()}
                  style={{
                    background: teamInput.trim()
                      ? "rgba(209,103,31,0.2)"
                      : "rgba(255,255,255,0.03)",
                    border: "1px solid var(--accent)",
                    color: teamInput.trim() ? "var(--accent-strong)" : "var(--muted)",
                    borderRadius: 8,
                    padding: "9px 20px",
                    cursor: teamInput.trim() ? "pointer" : "not-allowed",
                    fontWeight: 700,
                    fontSize: 14,
                  }}
                >
                  Join
                </button>
              </>
            )}
          </div>

          {/* ── Attack error ───────────────────────────────────────────────── */}
          {attackError && (
            <div
              style={{
                marginTop: 16,
                padding: "12px 16px",
                background: "rgba(192,57,43,0.1)",
                border: "1px solid rgba(192,57,43,0.4)",
                borderRadius: 8,
                fontSize: 13,
                color: "#e74c3c",
              }}
            >
              Attack error: {attackError}
            </div>
          )}

          {/* ── Scenario grid ──────────────────────────────────────────────── */}
          <div style={{ marginTop: 32 }}>
            <h2
              style={{
                margin: "0 0 20px",
                fontSize: 16,
                fontWeight: 700,
                color: "var(--muted)",
                textTransform: "uppercase",
                letterSpacing: "0.08em",
              }}
            >
              Attack Scenarios
            </h2>

            {scenariosLoading ? (
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: 40,
                  color: "var(--muted)",
                }}
              >
                <PulsingDot color="var(--accent)" />
                Loading scenarios…
              </div>
            ) : scenariosError ? (
              <div
                style={{
                  padding: "20px 24px",
                  background: "rgba(192,57,43,0.08)",
                  border: "1px solid rgba(192,57,43,0.3)",
                  borderRadius: 12,
                  color: "#e74c3c",
                  fontSize: 14,
                }}
              >
                Failed to load scenarios: {scenariosError}
              </div>
            ) : (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
                  gap: 20,
                }}
              >
                {scenarios.map((s) => (
                  <ScenarioCard
                    key={s.id}
                    scenario={s}
                    teamName={teamName}
                    isRunning={runningAttack === s.id}
                    onAttack={handleAttack}
                    result={results[s.id] ?? null}
                  />
                ))}
              </div>
            )}
          </div>

          {/* ── Leaderboard ────────────────────────────────────────────────── */}
          <div style={{ marginTop: 56 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: 16,
                flexWrap: "wrap",
                gap: 12,
              }}
            >
              <h2
                style={{
                  margin: 0,
                  fontSize: 16,
                  fontWeight: 700,
                  color: "var(--muted)",
                  textTransform: "uppercase",
                  letterSpacing: "0.08em",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                }}
              >
                Leaderboard
                <span style={{ fontSize: 11, color: "var(--muted)", fontWeight: 400, textTransform: "none", letterSpacing: 0 }}>
                  (auto-refresh 10s)
                </span>
              </h2>
              <button
                onClick={handleReset}
                disabled={resetting}
                style={{
                  background: "none",
                  border: "1px solid var(--border)",
                  color: "var(--muted)",
                  borderRadius: 6,
                  padding: "5px 12px",
                  cursor: resetting ? "not-allowed" : "pointer",
                  fontSize: 12,
                }}
              >
                {resetting ? "Resetting…" : "Reset"}
              </button>
            </div>

            <div
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                overflow: "hidden",
              }}
            >
              {lbLoading && leaderboard.length === 0 ? (
                <div
                  style={{
                    padding: 32,
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    color: "var(--muted)",
                    fontSize: 14,
                  }}
                >
                  <PulsingDot color="var(--accent)" />
                  Loading leaderboard…
                </div>
              ) : lbError ? (
                <div style={{ padding: 24, color: "#e74c3c", fontSize: 14 }}>
                  Failed to load leaderboard: {lbError}
                </div>
              ) : leaderboard.length === 0 ? (
                <div style={{ padding: 32, color: "var(--muted)", fontSize: 14, textAlign: "center" }}>
                  No attacks yet. Be the first to strike.
                </div>
              ) : (
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr
                      style={{
                        borderBottom: "1px solid var(--border)",
                        background: "rgba(255,255,255,0.02)",
                      }}
                    >
                      {["#", "Team", "Points", "Attacks", "Max Depth"].map((h, i) => (
                        <th
                          key={h}
                          style={{
                            padding: "12px 16px",
                            textAlign: i === 0 ? "center" : "left",
                            fontSize: 11,
                            fontWeight: 700,
                            color: "var(--muted)",
                            textTransform: "uppercase",
                            letterSpacing: "0.07em",
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {leaderboard.map((entry, idx) => {
                      const isMe = teamName && entry.team_name === teamName;
                      return (
                        <tr
                          key={entry.team_name}
                          style={{
                            borderBottom:
                              idx < leaderboard.length - 1
                                ? "1px solid var(--border)"
                                : "none",
                            background: isMe
                              ? "rgba(209,103,31,0.07)"
                              : "transparent",
                            transition: "background 0.2s",
                          }}
                        >
                          <td
                            style={{
                              padding: "14px 16px",
                              textAlign: "center",
                              fontSize: 13,
                              color:
                                idx === 0
                                  ? "#f1c40f"
                                  : idx === 1
                                  ? "#bdc3c7"
                                  : idx === 2
                                  ? "#cd6133"
                                  : "var(--muted)",
                              fontWeight: 700,
                            }}
                          >
                            {idx === 0 ? "🥇" : idx === 1 ? "🥈" : idx === 2 ? "🥉" : idx + 1}
                          </td>
                          <td
                            style={{
                              padding: "14px 16px",
                              fontSize: 14,
                              fontWeight: isMe ? 700 : 500,
                              color: isMe ? "var(--accent-strong)" : "var(--text)",
                            }}
                          >
                            {entry.team_name}
                            {isMe && (
                              <span
                                style={{
                                  marginLeft: 8,
                                  fontSize: 11,
                                  color: "var(--accent)",
                                  fontWeight: 600,
                                }}
                              >
                                (you)
                              </span>
                            )}
                          </td>
                          <td
                            style={{
                              padding: "14px 16px",
                              fontSize: 14,
                              fontWeight: 700,
                              color:
                                entry.total_points >= 10
                                  ? "#27ae60"
                                  : entry.total_points > 0
                                  ? "var(--accent-strong)"
                                  : "var(--muted)",
                            }}
                          >
                            {entry.total_points}
                          </td>
                          <td
                            style={{
                              padding: "14px 16px",
                              fontSize: 13,
                              color: "var(--muted)",
                            }}
                          >
                            {entry.attacks_attempted}
                          </td>
                          <td
                            style={{
                              padding: "14px 16px",
                              fontSize: 13,
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 6,
                              }}
                            >
                              {[0, 1, 2, 3, 4].map((lvl) => (
                                <div
                                  key={lvl}
                                  style={{
                                    width: 10,
                                    height: 10,
                                    borderRadius: 2,
                                    background:
                                      lvl <= entry.deepest_penetration
                                        ? lvl === 4
                                          ? "#27ae60"
                                          : "var(--accent)"
                                        : "rgba(255,255,255,0.08)",
                                  }}
                                />
                              ))}
                              <span
                                style={{
                                  marginLeft: 4,
                                  fontSize: 11,
                                  color: "var(--muted)",
                                }}
                              >
                                {entry.deepest_penetration}/4
                              </span>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}

export default RedTeamPage;
