import { useMemo, useState } from "react";
import type { TreasuryAgentRun } from "@treasury/shared";
import { api } from "../lib/api.js";
import type { DemoAttackResult } from "../lib/api.js";

type RunState = "ready" | "running" | "passed" | "attention" | "error";

type Scenario = {
  id: string;
  eyebrow: string;
  title: string;
  description: string;
  expected: string;
  attackId?: string;
};

const SECURITY_SCENARIOS: Scenario[] = [
  { id: "AT-6", eyebrow: "Identity", title: "Rogue agent", description: "Try to initiate a payment from a wallet with no Know Your Agent credential.", expected: "G1 KYA refuses the request before compliance runs.", attackId: "AT-6" },
  { id: "AT-2", eyebrow: "Credentials", title: "Forged KYC", description: "Accept a recipient credential from an attacker-controlled issuer.", expected: "The trusted-issuer check rejects the credential chain.", attackId: "AT-2" },
  { id: "AT-1", eyebrow: "Compliance", title: "Sanctioned counterparty", description: "Attempt a direct transfer to a known sanctioned address.", expected: "G2 sanctions hard-blocks it; approval cannot override it.", attackId: "AT-1" },
  { id: "AT-3", eyebrow: "AML", title: "Threshold structuring", description: "Shape a payment to 90% of the approval threshold.", expected: "The STRC typology detects just-under-threshold behavior.", attackId: "AT-3" },
  { id: "AT-4", eyebrow: "AML", title: "Shell entity", description: "Pay an opaque company in a secrecy jurisdiction.", expected: "Shell and jurisdiction signals accumulate in the AML score.", attackId: "AT-4" },
  { id: "AT-5", eyebrow: "Credentials", title: "PEP signal", description: "Issue a valid credential containing a politically exposed person flag.", expected: "Compliance reads the credential signal and escalates risk.", attackId: "AT-5" },
];

function ResultPill({ state }: { state: RunState }) {
  const labels: Record<RunState, string> = {
    ready: "Ready",
    running: "Running tools…",
    passed: "Guardrails held",
    attention: "Review result",
    error: "Could not run",
  };
  return <span className={`demo-status demo-${state}`}>{labels[state]}</span>;
}

function GuardrailTrail({ result }: { result: DemoAttackResult }) {
  return (
    <div className="demo-trail" aria-label="Guardrail decision trail">
      {result.guardrailTrail.map((step, index) => (
        <div className={`demo-trail-step ${step.passed ? "trail-pass" : "trail-stop"}`} key={`${step.guardrail}-${index}`}>
          <span>{step.passed ? "PASS" : "STOP"}</span>
          <div><strong>{step.guardrail.replaceAll("_", " ")}</strong><small>{step.detail}</small></div>
        </div>
      ))}
    </div>
  );
}

export function DemoLabPage() {
  const [states, setStates] = useState<Record<string, RunState>>({});
  const [results, setResults] = useState<Record<string, DemoAttackResult>>({});
  const [agentRun, setAgentRun] = useState<TreasuryAgentRun | null>(null);
  const [coverResult, setCoverResult] = useState<{ description: string; amount: string; narration: string | null } | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});

  const completed = useMemo(() => Object.values(states).filter((state) => state === "passed" || state === "attention").length, [states]);
  const total = SECURITY_SCENARIOS.length + 2;

  const setRunning = (id: string) => {
    setStates((current) => ({ ...current, [id]: "running" }));
    setErrors((current) => ({ ...current, [id]: "" }));
  };

  const runAttack = async (scenario: Scenario) => {
    setRunning(scenario.id);
    try {
      const result = await api.runDemoAttack(scenario.attackId!);
      setResults((current) => ({ ...current, [scenario.id]: result }));
      setStates((current) => ({ ...current, [scenario.id]: result.outcome === "settled" ? "attention" : "passed" }));
    } catch (cause) {
      setErrors((current) => ({ ...current, [scenario.id]: String(cause) }));
      setStates((current) => ({ ...current, [scenario.id]: "error" }));
    }
  };

  const runAutonomousPayment = async () => {
    setRunning("autonomous");
    try {
      await api.seedMaersk();
      const run = await api.runController(true, true);
      setAgentRun(run);
      setStates((current) => ({ ...current, autonomous: run.goalsTriggered > 0 ? "passed" : "attention" }));
    } catch (cause) {
      setErrors((current) => ({ ...current, autonomous: String(cause) }));
      setStates((current) => ({ ...current, autonomous: "error" }));
    }
  };

  const runCover = async () => {
    setRunning("cover");
    try {
      const result = await api.coverRunDemo41();
      setCoverResult({ description: result.description, amount: result.payout.amountPaid, narration: result.narration });
      setStates((current) => ({ ...current, cover: "passed" }));
    } catch (cause) {
      setErrors((current) => ({ ...current, cover: String(cause) }));
      setStates((current) => ({ ...current, cover: "error" }));
    }
  };

  return (
    <div className="demo-lab">
      <header className="demo-hero">
        <div>
          <span className="eyebrow">Interactive judge environment</span>
          <h1>Test the system.<br />Try to break it.</h1>
          <p>Every button sends controlled inputs through the running API and its deterministic policy tools. The AI may narrate the outcome; it never decides or signs.</p>
        </div>
        <div className="demo-score" aria-label={`${completed} of ${total} scenarios completed`}>
          <strong>{completed}<small>/{total}</small></strong>
          <span>scenarios tested</span>
          <div><i style={{ width: `${(completed / total) * 100}%` }} /></div>
        </div>
      </header>

      <section className="demo-principles" aria-label="System guarantees">
        <div><span>01</span><strong>Identity</strong><small>KYA agent + KYC recipient</small></div>
        <div><span>02</span><strong>Deterministic policy</strong><small>Code controls every branch</small></div>
        <div><span>03</span><strong>Insured execution</strong><small>Measurable loss, bounded payout</small></div>
      </section>

      <section className="demo-section">
        <div className="demo-section-head">
          <div><span className="eyebrow">The qualification shot</span><h2>Autonomous agent payment</h2></div>
          <p>The controller discovers due service goals and attempts settlement without a human clicking Pay.</p>
        </div>
        <article className="demo-feature-card">
          <div className="demo-feature-copy">
            <ResultPill state={states.autonomous ?? "ready"} />
            <h3>Run the treasury fleet</h3>
            <p>Seeds scoped business agents, evaluates their due goals, checks spending policy, and executes eligible x402 service payments.</p>
            <button className="demo-run" type="button" onClick={runAutonomousPayment} disabled={states.autonomous === "running"}>
              {states.autonomous === "running" ? "Agent is evaluating…" : agentRun ? "Run another cycle" : "Run autonomous cycle"}
            </button>
            {errors.autonomous && <p className="demo-error" role="alert">{errors.autonomous}</p>}
          </div>
          <div className="demo-proof-panel">
            {agentRun ? (
              <>
                <span className="eyebrow">Backend response</span>
                <div className="demo-flow" aria-label="Autonomous payment execution flow">
                  {[
                    ["01", "Discover", `${agentRun.goalsEvaluated} due goals`],
                    ["02", "KYA + scope", "Identity boundary"],
                    ["03", "Policy", "Limits enforced"],
                    ["04", "x402", `${agentRun.goalsTriggered} eligible`],
                    ["05", "XRPL", "No funds moved"],
                  ].map(([number, label, detail], index) => (
                    <div className={`demo-flow-node ${index < 3 || agentRun.goalsTriggered > 0 ? "flow-active" : ""}`} key={number}>
                      <span>{number}</span><strong>{label}</strong><small>{detail}</small>
                    </div>
                  ))}
                </div>
                <div className="demo-metrics"><div><strong>{agentRun.goalsEvaluated}</strong><span>evaluated</span></div><div><strong>{agentRun.goalsTriggered}</strong><span>eligible</span></div><div><strong>{agentRun.paymentsSkipped.length}</strong><span>stopped</span></div></div>
                <ol className="demo-log">{agentRun.triggerLog.slice(0, 7).map((line, index) => <li key={index}>{line}</li>)}</ol>
                {agentRun.narration && <p className="demo-narration">“{agentRun.narration}”</p>}
              </>
            ) : <div className="demo-empty-proof"><strong>No pre-baked result</strong><span>Run the scenario to see the API's live decision trail.</span></div>}
          </div>
        </article>
      </section>

      <section className="demo-section">
        <div className="demo-section-head">
          <div><span className="eyebrow">Defense in depth</span><h2>Credential & policy stress tests</h2></div>
          <p>Choose any attack. A safe result is a refusal or controlled escalation—not a theatrical success screen.</p>
        </div>
        <div className="demo-scenario-grid">
          {SECURITY_SCENARIOS.map((scenario) => {
            const result = results[scenario.id];
            const state = states[scenario.id] ?? "ready";
            return (
              <article className={`demo-scenario-card ${result ? "has-result" : ""}`} key={scenario.id}>
                <div className="demo-card-top"><span className="demo-index">{scenario.id}</span><ResultPill state={state} /></div>
                <span className="eyebrow">{scenario.eyebrow}</span>
                <h3>{scenario.title}</h3>
                <p>{scenario.description}</p>
                <div className="demo-expected"><span>Expected control</span><strong>{scenario.expected}</strong></div>
                <button className="demo-run demo-run-secondary" type="button" onClick={() => runAttack(scenario)} disabled={state === "running"}>
                  {state === "running" ? "Running…" : result ? "Run again" : "Test guardrails"}
                </button>
                {errors[scenario.id] && <p className="demo-error" role="alert">{errors[scenario.id]}</p>}
                {result && <div className="demo-result"><div className="demo-result-head"><strong>{result.outcome}</strong><span>Depth {result.depthReached}/4 · {result.pointsEarned} pts</span></div><GuardrailTrail result={result} /><p>{result.verdict}</p></div>}
              </article>
            );
          })}
        </div>
      </section>

      <section className="demo-section">
        <div className="demo-section-head">
          <div><span className="eyebrow">The recovery layer</span><h2>Insure what policy cannot prevent</h2></div>
          <p>A deterministic reconciler—not the LLM—compares expected and executed payment facts.</p>
        </div>
        <article className="demo-feature-card demo-cover-card">
          <div className="demo-feature-copy">
            <ResultPill state={states.cover ?? "ready"} />
            <h3>Underpayment hallucination</h3>
            <div className="demo-equation"><div><span>Invoice</span><strong>500</strong></div><b>−</b><div><span>Paid</span><strong>480</strong></div><b>=</b><div className="demo-loss"><span>Covered loss</span><strong>20 RLUSD</strong></div></div>
            <p>The claim endpoint derives all financial facts server-side, applies eligibility and capacity rules, and tops up the merchant.</p>
            <button className="demo-run" type="button" onClick={runCover} disabled={states.cover === "running"}>{states.cover === "running" ? "Reconciling…" : coverResult ? "Run another claim" : "Simulate & settle claim"}</button>
            {errors.cover && <p className="demo-error" role="alert">{errors.cover}</p>}
          </div>
          <div className="demo-proof-panel">
            {coverResult ? <><span className="eyebrow">Settled result</span><strong className="demo-payout">+{coverResult.amount} <small>RLUSD</small></strong><p>{coverResult.description}</p>{coverResult.narration && <p className="demo-narration">“{coverResult.narration}”</p>}</> : <div className="demo-empty-proof"><strong>No claim created yet</strong><span>The result will come from the connected insurance service.</span></div>}
          </div>
        </article>
      </section>

      <footer className="demo-footer"><strong>The AI decides nothing about money.</strong><span>Credentials authorize. Code decides. XRPL settles. Insurance recovers.</span></footer>
    </div>
  );
}
