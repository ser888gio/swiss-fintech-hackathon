import { useEffect, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { FeatureCollection } from "geojson";
// Import world-atlas topology directly — no network fetch needed
// eslint-disable-next-line @typescript-eslint/ban-ts-comment
// @ts-ignore — world-atlas ships CommonJS without type declarations
import worldData from "world-atlas/countries-110m.json";
import {
  BANNED_COMPANIES,
  SANCTIONED_COUNTRIES,
  SANCTIONED_PERSONS,
} from "../data/sanctions.js";

const TIER_COLOR: Record<string, string> = {
  blacklist: "#ef4444",
  greylist: "#f59e0b",
};

// world-atlas uses ISO 3166-1 numeric IDs as feat.id (properties is always {})
const ISO_NUMERIC_TO_A2: Record<string, string> = {
  "004": "AF", "112": "BY", "180": "CD", "192": "CU", "148": "TD",
  "364": "IR", "332": "HT", "408": "KP", "418": "LA", "104": "MM",
  "586": "PK", "643": "RU", "728": "SS", "760": "SY", "862": "VE",
  "887": "YE", "716": "ZW", "548": "VU",
};

const COUNTRY_MAP = new Map(SANCTIONED_COUNTRIES.map((c) => [c.code, c]));

// Convert TopoJSON → GeoJSON once at module load (synchronous, no fetch)
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const GEO_FEATURES = ((feature(worldData as any, (worldData as any).objects.countries) as unknown) as FeatureCollection).features as object[];

export function SanctionsPage() {
  const globeRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const globeInstanceRef = useRef<any>(null);
  const [globeReady, setGlobeReady] = useState(false);
  const [globeError, setGlobeError] = useState(false);

  useEffect(() => {
    if (!globeRef.current || globeInstanceRef.current) return;

    import("react-globe.gl")
      .then((mod) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const Globe = mod.default as any;
        const el = globeRef.current!;
        const globe = Globe()(el);

        globe
          // No CDN textures — dark sphere + atmospheric glow looks clean
          .globeImageUrl(null)
          .atmosphereColor("#1e40af")
          .atmosphereAltitude(0.18)
          .backgroundColor("#05070e")
          .polygonsData(GEO_FEATURES)
          .polygonAltitude(0.006)
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .polygonCapColor((feat: any) => {
            const a2 = ISO_NUMERIC_TO_A2[String(feat?.id ?? "")];
            const entry = a2 ? COUNTRY_MAP.get(a2) : undefined;
            return entry ? TIER_COLOR[entry.tier] : "rgba(255,255,255,0.07)";
          })
          .polygonSideColor(() => "rgba(0,0,0,0.15)")
          .polygonStrokeColor(() => "#0f172a")
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .polygonLabel((feat: any) => {
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
          })
          .width(el.clientWidth || 800)
          .height(520);

        globe.controls().autoRotate = true;
        globe.controls().autoRotateSpeed = 0.5;
        globeInstanceRef.current = globe;
        setGlobeReady(true);
      })
      .catch(() => setGlobeError(true));
  }, []);

  return (
    <section className="send-flow" style={{ gridTemplateColumns: "1fr" }} aria-label="Sanctions &amp; Watchlist">
      <div style={{ padding: "0.55rem 0.75rem", marginBottom: "1rem", borderBottom: "1px solid var(--border)", color: "var(--muted)", fontSize: "0.82rem", lineHeight: 1.5 }}>
        <strong style={{ color: "var(--paper)" }}>Sanctions &amp; Watchlist</strong> — illustrative reference data based on FATF, OFAC, EU, and UN public lists. Not a live sanctions feed. The treasury agent enforces a curated deterministic policy subset on every payment.
      </div>

      <div className="send-topbar">
        <div>
          <span className="eyebrow">Compliance · Geopolitical risk</span>
          <h1>Sanctions watchlist</h1>
        </div>
        <span className="policy-pill">code decides · LLM narrates</span>
      </div>

      {/* Globe — full width, centered, above tables */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: "1.5rem" }}>
        {/* Legend */}
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

        <div style={{ position: "relative", width: "100%", height: 520, borderRadius: 12, overflow: "hidden", background: "#05070e" }}>
          {!globeReady && !globeError && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", fontSize: "0.85rem" }}>
              Loading globe…
            </div>
          )}
          {globeError && (
            <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)", fontSize: "0.85rem", flexDirection: "column", gap: "0.5rem" }}>
              <span>Globe failed to initialise (WebGL required).</span>
              <span style={{ fontSize: "0.75rem" }}>Country lists below remain accurate.</span>
            </div>
          )}
          <div
            ref={globeRef}
            style={{ width: "100%", height: "100%" }}
            aria-label="World globe highlighting sanctioned and high-risk countries"
          />
        </div>
      </div>

      {/* Dashboard tables */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1.25rem" }}>
        {/* Banned companies */}
        <div className="gate-scenario" style={{ padding: "1rem" }}>
          <div className="section-heading" style={{ marginBottom: "0.6rem" }}>
            <span className="eyebrow">Entity screening</span>
            <strong>Banned companies ({BANNED_COMPANIES.length})</strong>
          </div>
          <table style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse" }}>
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

        {/* Sanctioned persons */}
        <div className="gate-scenario" style={{ padding: "1rem" }}>
          <div className="section-heading" style={{ marginBottom: "0.6rem" }}>
            <span className="eyebrow">PEP / SDN screening</span>
            <strong>Sanctioned persons ({SANCTIONED_PERSONS.length})</strong>
          </div>
          <table style={{ width: "100%", fontSize: "0.78rem", borderCollapse: "collapse" }}>
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
    </section>
  );
}
