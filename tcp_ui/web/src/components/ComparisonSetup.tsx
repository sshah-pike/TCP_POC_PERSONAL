import { useEffect, useState } from "react";
import { getResumePreview, startComparison } from "../api";
import type { Meta, ResumePreview, Variant } from "../types";

interface Props {
  runId: string;
  meta: Meta;
  onStarted: (comparisonId: string) => void;
  onCancel: () => void;
}

/** Choose models x evidence modes to compare on the SAME saved imagery, georeference and OSM evidence. */
export default function ComparisonSetup({ runId, meta, onStarted, onCancel }: Props) {
  const profiles = meta.foundry_profiles;
  const [chosen, setChosen] = useState<string[]>(profiles.filter((p) => p.available).map((p) => p.name));
  const [modes, setModes] = useState<string[]>(["multi"]);
  const [visionModes, setVisionModes] = useState<string[]>(["baseline", "grounded_v2"]);
  const [osmClaims, setOsmClaims] = useState(false);
  const [centerline, setCenterline] = useState(false);
  const [preview, setPreview] = useState<ResumePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getResumePreview(runId, "vision", null).then(setPreview).catch((e: Error) => setError(e.message));
  }, [runId]);

  const toggle = (list: string[], set: (v: string[]) => void, n: string) =>
    set(list.includes(n) ? list.filter((x) => x !== n) : [...list, n]);
  const variants: Variant[] = modes.flatMap((m) => visionModes.map((v) => ({
    evidence_mode: m, vision_mode: v, osm_claims: v === "grounded_v2" && osmClaims,
    centerline_views: m === "multi" && v === "grounded_v2" && centerline })));
  const columns = chosen.length * variants.length;

  async function start() {
    setBusy(true); setError(null);
    try {
      onStarted(await startComparison(runId, chosen, variants));
    } catch (e) {
      setError((e as Error).message); setBusy(false);
    }
  }

  const blocked = (preview?.legacy || preview?.moved_earlier) ?? false;
  return (
    <div className="card resume">
      <h2>Compare models</h2>
      <div className="muted small">
        Each combination runs as its own child run from the AI stage on the exact same saved overview image,
        georeference, OSM evidence and operator inputs. Multi-resolution views are acquired once and shared by every
        model. No new analysis-imagery or OSM calls. No model is ranked or selected.
      </div>
      {error && <div className="banner bad small">{error}</div>}
      {preview?.legacy && <div className="banner bad small">{preview.legacy_reason} – not eligible for comparison.</div>}
      {!preview?.legacy && preview?.moved_earlier && <div className="banner warn small">Not available: {preview.move_reason}</div>}
      {preview && !blocked && (
        <>
          <h3>Reused artifacts</h3>
          <table className="tbl small">
            <thead><tr><th>Stage</th><th>Source run</th><th>Artifact</th><th>Hash</th></tr></thead>
            <tbody>
              {preview.reused.filter((r) => !r.conditional).map((r) => (
                <tr key={r.artifact}><td>{r.title}</td><td className="mono">{r.source_run}</td>
                  <td className="mono">{r.artifact}</td><td className="mono">{r.sha256.slice(0, 16)}…</td></tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <h3>Models</h3>
      {profiles.map((p) => (
        <label key={p.name} className="profile">
          <input type="checkbox" disabled={!p.available || blocked} checked={chosen.includes(p.name)}
                 onChange={() => toggle(chosen, setChosen, p.name)} />{" "}
          <b>{p.display_name}</b> <span className="muted small">deployment {p.deployment} · {p.api}
          {!p.available && (p.backend_implemented ? " · disabled" : " · API not implemented")}</span>
        </label>
      ))}
      <h3>AI evidence</h3>
      {[["single", "single-resolution (overview only - current baseline)"],
        ["multi", "multi-resolution (overview + work-area close-up + 2 corridor views; acquired once, shared)"]].map(([m, l]) => (
        <label key={m} className="profile">
          <input type="checkbox" disabled={blocked} checked={modes.includes(m)} onChange={() => toggle(modes, setModes, m)} /> {l}
        </label>
      ))}
      <h3>Vision mode</h3>
      {[["baseline", "baseline (current prompt - unchanged)"],
        ["grounded_v2", "grounded_v2 (metres, annotated copies, definitions, rubric, evidence statements, consistency checks)"]].map(([m, l]) => (
        <label key={m} className="profile">
          <input type="checkbox" disabled={blocked} checked={visionModes.includes(m)} onChange={() => toggle(visionModes, setVisionModes, m)} /> {l}
        </label>
      ))}
      <label className="profile"><input type="checkbox" disabled={blocked || !visionModes.includes("grounded_v2")} checked={osmClaims}
        onChange={(e) => setOsmClaims(e.target.checked)} /> grounded_v2: supply OSM side-way claims for visual verification</label>
      <label className="profile"><input type="checkbox" disabled={blocked || !visionModes.includes("grounded_v2") || !modes.includes("multi")}
        checked={centerline} onChange={(e) => setCenterline(e.target.checked)} /> grounded_v2 multi: corridor views along the OSM centerline</label>
      <div className="buttons">
        <button className="primary inline" disabled={busy || blocked || columns < 2} onClick={start}>
          {busy ? "Starting…" : `Start comparison (${columns} runs)`}
        </button>
        <button className="link" onClick={onCancel}>Cancel</button>
        {columns < 2 && <span className="muted small">select at least two model/evidence combinations</span>}
      </div>
    </div>
  );
}
