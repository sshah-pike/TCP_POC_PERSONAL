import { useState } from "react";
import type { Json } from "./types";
import { Details, KV, Sev, StateBadge, fmt } from "./parts";

export interface Choice { action: string; label: string; value?: unknown; input?: string; range?: [number, number]; reason_required?: boolean }

// One review card. Buttons call deterministic backend actions (no AI). onChoose undefined = read-only.
export default function ReviewCard({ f, staged, onChoose }: { f: Json; staged?: Json; onChoose?: (c: Choice, extra: Json) => void }) {
  const [input, setInput] = useState("");
  const [reason, setReason] = useState("");
  const [station, setStation] = useState("");
  const [side, setSide] = useState("RIGHT");
  const choose = (c: Choice) => {
    if (!onChoose) return;
    const extra: Json = { reason: reason || undefined };
    if (c.input === "int" || c.input === "float") extra.value = c.input === "int" ? parseInt(input, 10) : parseFloat(input);
    if (c.input === "station_side") { extra.station_m = parseFloat(station); extra.side = side; }
    onChoose(c, extra);
  };
  const needsReason = (f.choices as Choice[]).some((c) => c.reason_required) || ["SITE_FACT", "FEATURE"].includes(f.category);
  return (
    <div className={`sme-card sme-card-${f.state}`}>
      <div className="sme-card-head">
        <StateBadge state={f.state} /> <b>{f.label}</b> <Sev s={f.severity} />
        <span className="mono muted small"> {f.finding_id}</span>
      </div>
      <KV rows={[
        ["Current / detected value", fmt(f.value)],
        ["Confidence", f.confidence == null ? "—" : f.confidence.toFixed(2)],
        ["Evidence source", (f.evidence_sources ?? []).join(", ")],
        ["Reason for review", f.reason ?? (f.reason_code ? f.reason_code : "—")],
        ["Applicable rule", f.rule_id ? `${f.rule_id}: ${f.rule_text ?? ""}` : (f.rule_refs ?? []).join(", ")],
        ["Entity", <span className="mono">{f.entity_id}</span>],
        ["Station", f.station_m == null ? undefined : `${f.station_m} m`],
      ]} />
      {staged && <div className="banner info small">Staged decision: <b>{staged.action}</b> {staged.value !== undefined ? `→ ${fmt(staged.value)}` : ""} (not committed)</div>}
      {f.choices?.length > 0 && (
        <div className="sme-choices">
          {(f.choices as Choice[]).some((c) => c.input === "int" || c.input === "float") &&
            <input className="sme-input" placeholder="value" value={input} onChange={(e) => setInput(e.target.value)} />}
          {(f.choices as Choice[]).some((c) => c.input === "station_side") && <>
            <input className="sme-input" placeholder="station m" value={station} onChange={(e) => setStation(e.target.value)} />
            <select value={side} onChange={(e) => setSide(e.target.value)}><option>LEFT</option><option>RIGHT</option><option>BOTH</option></select>
          </>}
          {needsReason && onChoose && <input className="sme-input wide" placeholder="reason (required for corrections / rejections)" value={reason} onChange={(e) => setReason(e.target.value)} />}
          <div className="buttons">
            {(f.choices as Choice[]).map((c, i) => (
              <button key={i} className="btn small" disabled={!onChoose} title={onChoose ? "" : "read-only review"} onClick={() => choose(c)}>{c.label}</button>
            ))}
          </div>
        </div>
      )}
      {f.observations?.length > 0 && (
        <Details title="Machine evidence (observations)">
          <pre className="viewer short">{JSON.stringify(f.observations, null, 1)}</pre>
        </Details>
      )}
    </div>
  );
}
