import { Component, type ReactNode, Suspense, lazy, useEffect, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { FeatureCollection } from "geojson";
// Import world-atlas topology directly — no network fetch
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore — world-atlas has no type declarations
import worldData from "world-atlas/countries-110m.json";
import {
  BANNED_COMPANIES,
  SANCTIONED_COUNTRIES,
  SANCTIONED_PERSONS,
} from "../data/sanctions.js";

// --- Data setup ----------------------------------------------------------

const TIER_COLOR: Record<string, string> = {
  blacklist: "#ef4444",
  greylist: "#f59e0b",
};

// world-atlas numeric IDs → ISO alpha-2 (only countries in our dataset)
const ISO_NUMERIC_TO_A2: Record<string, string> = {
  "004": "AF", "112": "BY", "180": "CD", "192": "CU", "148": "TD",
  "364": "IR", "332": "HT", "408": "KP", "418": "LA", "104": "MM",
  "586": "PK", "643": "RU", "728": "SS", "760": "SY", "862": "VE",
  "887": "YE", "716": "ZW", "548": "VU",
};

const COUNTRY_MAP = new Map(SANCTIONED_COUNTRIES.map((c) => [c.code, c]));

// Convert TopoJSON → GeoJSON features once at module load (synchronous)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const GEO_FEATURES = ((feature(worldData as any, (worldData as any).objects.countries) as unknown) as FeatureCollection).features;

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function capColor(feat: any): string {
  const a2 = ISO_NUMERIC_TO_A2[String(feat?.id ?? "")];
  const entry = a2 ? COUNTRY_MAP.get(a2) : undefined;
  return entry ? TIER_COLOR[entry.tier] : "rgba(255,255,255,0.07)";
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function polygonLabel(feat: any): string {
  const a2 = ISO_NUMERIC_TO_A2[String(feat?.id ?? "")];
  const entry = a2 ? COUNTRY_MAP.get(a2) : undefined;
  if (!entry) return "";
  const badge =
    entry.tier === "blacklist"
      ? '<span style="color:#ef4444;font-weight:600">● BLOCKED</span>'
      : '<span style="color:#f59e0b;font-weight:600">● REVIEW</span>';
  return `<div style="background:rgba(0,0,0,0.9);padding:8px 10px;border-radius:6px;font-size:12px;max-width:240px;line-height:1.55">
    <strong style="color:#f9fafb">${entry.name}</strong> ${badge}<br/>
    <span style="color:#9ca3af">${entry.rationale}</span><br/>
    <span style="color:#6b7280;font-size:11px">${entry.sources.join(" · ")}</span>
  </div>`;
}

// --- Globe component (lazy-loaded so three.js doesn't block first paint) ---

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const Globe = lazy(() => import("react-globe.gl").then((m) => ({ default: m.default as any })));

function GlobeView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setWidth(el.offsetWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const h = width > 0 ? Math.min(480, Math.max(240, Math.round(width * 0.52))) : 0;

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const G = Globe as any;
  return (
    <div ref={containerRef} style={{ width: "100%", height: h || undefined, display: "flex", justifyContent: "center", overflow: "hidden" }}>
      {width > 0 && (
        <G
          globeImageUrl={null}
          atmosphereColor="#1e40af"
          atmosphereAltitude={0.18}
          backgroundColor="#05070e"
          polygonsData={GEO_FEATURES}
          polygonAltitude={0.006}
          polygonCapColor={capColor}
          polygonSideColor={() => "rgba(0,0,0,0.15)"}
          polygonStrokeColor={() => "#0f172a"}
          polygonLabel={polygonLabel}
          width={width}
          height={h}
        />
      )}
    </div>
  );
}

// --- Error boundary to catch WebGL or import failures -------------------

interface EBState { error: boolean }
class GlobeErrorBoundary extends Component<{ children: ReactNode }, EBState> {
  state: EBState = { error: false };
  static getDerivedStateFromError() { return { error: true }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: "0.5rem", color: "var(--muted)", fontSize: "0.85rem" }}>
          <span>Globe failed to initialise (WebGL required).</span>
          <span style={{ fontSize: "0.75rem" }}>Country lists below remain accurate.</span>
        </div>
      );
    }
    return this.props.children;
  }
}

// --- Page ----------------------------------------------------------------

export function SanctionsPage() {
  return (
    <section className="send-flow" style={{ gridTemplateColumns: "1fr" }} aria-label="Sanctions &amp; Watchlist">
      <div style={{ padding: "0.55rem 0.75rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: "0.82rem", lineHeight: 1.5 }}>
        <strong style={{ color: "var(--paper)" }}>Sanctions &amp; Watchlist</strong> — illustrative reference data based on FATF, OFAC, EU, and UN public lists. Not a live sanctions feed. The treasury agent enforces a curated deterministic policy subset on every payment. The agent is forbidden to deal with sanctioned persons, companies or countries.
      </div>

      <div className="send-topbar">
        <div>
          <span className="eyebrow">Compliance · Geopolitical risk</span>
          <h1>Sanctions watchlist</h1>
        </div>
      </div>

      {/* Globe — full width, centered, above tables */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: "1.5rem" }}>
        <div style={{ display: "flex", gap: "1.5rem", marginBottom: "0.75rem", fontSize: "0.8rem", color: "var(--muted)", justifyContent: "center" }}>
          <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#ef4444", flexShrink: 0, display: "inline-block" }} />
            Blocked — FATF call for action
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
            <span style={{ width: 10, height: 10, borderRadius: "50%", background: "#f59e0b", flexShrink: 0, display: "inline-block" }} />
            Review required — grey-list / sectoral sanctions
          </span>
        </div>

        <div style={{ position: "relative", width: "100%", borderRadius: 12, overflow: "hidden", background: "#05070e" }}>
          <GlobeErrorBoundary>
            <Suspense fallback={
              <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", fontSize: "0.85rem" }}>
                Loading globe…
              </div>
            }>
              <GlobeView />
            </Suspense>
          </GlobeErrorBoundary>
        </div>
      </div>

      {/* Dashboard tables */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1.25rem" }}>
        <div className="gate-scenario" style={{ padding: "1rem", minWidth: 0 }}>
          <div className="section-heading" style={{ marginBottom: "0.6rem" }}>
            <span className="eyebrow">Entity screening</span>
            <strong>Banned companies ({BANNED_COMPANIES.length})</strong>
          </div>
          <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
            <table style={{ width: "100%", minWidth: 320, fontSize: "0.78rem", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "var(--muted)", textAlign: "left" }}>
                  <th style={{ paddingBottom: "0.4rem", fontWeight: 500 }}>Name</th>
                  <th style={{ paddingBottom: "0.4rem", fontWeight: 500 }}>Country</th>
                  <th style={{ paddingBottom: "0.4rem", fontWeight: 500 }}>Program</th>
                  <th style={{ paddingBottom: "0.4rem", fontWeight: 500, whiteSpace: "nowrap" }}>Listed</th>
                </tr>
              </thead>
              <tbody>
                {BANNED_COMPANIES.map((c, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "0.3rem 0.5rem 0.3rem 0", color: "var(--paper)" }}>{c.name}</td>
                    <td style={{ padding: "0.3rem 0.5rem", color: "var(--muted)" }}>{c.country}</td>
                    <td style={{ padding: "0.3rem 0.5rem", color: "var(--muted)", fontSize: "0.72rem" }}>{c.program}</td>
                    <td style={{ padding: "0.3rem 0 0.3rem 0.5rem", color: "var(--muted)", whiteSpace: "nowrap" }}>{c.listedSince}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="gate-scenario" style={{ padding: "1rem", minWidth: 0 }}>
          <div className="section-heading" style={{ marginBottom: "0.6rem" }}>
            <span className="eyebrow">PEP / SDN screening</span>
            <strong>Sanctioned persons ({SANCTIONED_PERSONS.length})</strong>
          </div>
          <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
            <table style={{ width: "100%", minWidth: 320, fontSize: "0.78rem", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ color: "var(--muted)", textAlign: "left" }}>
                  <th style={{ paddingBottom: "0.4rem", fontWeight: 500 }}>Name</th>
                  <th style={{ paddingBottom: "0.4rem", fontWeight: 500 }}>Country</th>
                  <th style={{ paddingBottom: "0.4rem", fontWeight: 500 }}>Role</th>
                  <th style={{ paddingBottom: "0.4rem", fontWeight: 500, whiteSpace: "nowrap" }}>Listed</th>
                </tr>
              </thead>
              <tbody>
                {SANCTIONED_PERSONS.map((p, i) => (
                  <tr key={i} style={{ borderTop: "1px solid var(--border)" }}>
                    <td style={{ padding: "0.3rem 0.5rem 0.3rem 0", color: "var(--paper)" }}>{p.name}</td>
                    <td style={{ padding: "0.3rem 0.5rem", color: "var(--muted)" }}>{p.country}</td>
                    <td style={{ padding: "0.3rem 0.5rem", color: "var(--muted)", fontSize: "0.72rem" }}>{p.role}</td>
                    <td style={{ padding: "0.3rem 0 0.3rem 0.5rem", color: "var(--muted)", whiteSpace: "nowrap" }}>{p.listedSince}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </section>
  );
}
