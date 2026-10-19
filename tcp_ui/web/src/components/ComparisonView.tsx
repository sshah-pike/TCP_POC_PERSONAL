import { Fragment, useEffect, useState, type ReactNode } from "react";
import { getComparison } from "../api";
import { decisionClass, fmtMs, fmtUsd } from "../format";
import type { ComparisonColumn, ComparisonReport } from "../types";
import EvaluationPanel from "./EvaluationPanel";
import ScrollX from "./ScrollX";

interface Props {
  comparisonId: string;
  onOpenRun: (runId: string) => void;
}

const show = (v: unknown): string => (v === null || v === undefined ? "null (unknown)" : typeof v === "object" ? JSON.stringify(v) : String(v));
const tok = (c: ComparisonColumn, k: string) => (c.usage && c.usage[k] !== undefined ? c.usage[k].toLocaleString() : "Not Available");

/** Side-by-side factual comparison of per-model child runs. No ranking, no "best". */
export default function ComparisonView({ comparisonId, onOpenRun }: Props) {
  const [rep, setRep] = useState<ComparisonReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false; let timer: number | undefined;
    const poll = async () => {
      try {
        const r = await getComparison(comparisonId);
        if (cancelled) return;
        setRep(r); setError(null);
        if (!r.complete) timer = window.setTimeout(poll, 2000);
      } catch (e) {
        if (!cancelled) { setError((e as Error).message); timer = window.setTimeout(poll, 3000); }
      }
    };
    poll();
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); };
  }, [comparisonId]);

  if (!rep) return <div className="card">{error ? `Cannot load comparison: ${error}` : "Loading…"}</div>;
  const cols = rep.columns;
  const headerRows: [string, (c: ComparisonColumn) => ReactNode][] = [
    ["Evidence", (c) => (c.evidence_mode === "multi" ? "multi-resolution" : "single-resolution")],
    ["Images sent", (c) => (c.views.length ? `overview + ${c.views.join(", ")}` : "overview only")],
    ["API family", (c) => c.backend ?? "—"],
    ["Deployment", (c) => c.deployment ?? "—"],
    ["Model (reported)", (c) => c.model ?? "Not Available"],
    ["Run status", (c) => c.state ?? "—"],
    ["Final decision", (c) => <span className={`pill ${decisionClass(c.decision)}`}>{c.decision ?? "—"}</span>],
    ["Reason codes", (c) => (c.reason_codes.length ? c.reason_codes.join(", ") : "—")],
    ["AI status", (c) => (c.ai_status === "OK" ? "OK" : `${c.ai_status ?? "—"}${c.ai_error ? `: ${c.ai_error.error_code}` : ""}`)],
    ["Schema / normalization errors", (c) => (c.schema_errors?.length ? c.schema_errors.join("; ") : "none")],
    ["AI duration", (c) => fmtMs(c.ai_duration_ms)],
    ["Input / output tokens", (c) => `${tok(c, "input_tokens")} / ${tok(c, "output_tokens")}`],
    ["Cache write / read tokens", (c) => `${tok(c, "cache_creation_input_tokens")} / ${tok(c, "cache_read_input_tokens")}`],
    ["Estimated cost", (c) => (c.estimated_cost_usd !== null ? `${fmtUsd(c.estimated_cost_usd)} (Estimated Cost)` : "Not Available")],
    ["Image quality (model)", (c) => c.image_quality ?? "—"],
    ["Fusion", (c) => (c.fusion ? `${c.fusion.inputs_complete ? "inputs complete" : "inputs incomplete"}, ${c.fusion.conflicts} conflicts` : "not run")],
    ["Eligibility", (c) => c.eligibility?.decision ?? "not run"],
    ["Downstream generation", (c) => (c.draft_generated ? `draft ${c.plan_id}` : "no draft")],
    ["Resolved / unresolved / low-confidence fields", (c) => `${c.metrics.resolved} / ${c.metrics.unresolved} / ${c.metrics.low_confidence}`],
    [`Confidence below ${rep.confidence_threshold}`, (c) => (c.metrics.below_threshold.length ? c.metrics.below_threshold.join(", ") : "none")],
    ["Reused evidence (API call: No)", (c) => c.reused.map((r) => `${r.kind} from ${r.source_run}`).join("; ") || "—"],
    ["New map / OSM calls", (c) => c.new_external_calls.length || "none"],
  ];
  const sections = ["decision", "observation", "confidence", "site_model"];
  return (
    <>
      <div className="card">
        <div className="runhead">
          <h2>Model comparison <span className="mono">{rep.comparison_id}</span></h2>
          <span className={`pill ${rep.complete ? "ok" : "run"}`}>{rep.complete ? "COMPLETE" : "RUNNING"}</span>
        </div>
        <div className="muted small">
          Source run <button className="link mono" onClick={() => onOpenRun(rep.source_run_id)}>{rep.source_run_id}</button>
          {" "}· {rep.note}
        </div>
        <div className="small">Phase: <b>{rep.phase}</b>
          {rep.prep && <> · multi-resolution evidence: {rep.prep.state === "RUNNING" ? "acquiring…" : rep.prep.ok ? `prepared (${(rep.prep.views ?? []).join(", ")})` : `FAILED – ${rep.prep.error}`}</>}
        </div>
        {rep.skipped.map((s) => (
          <div key={s.profile + s.evidence_mode} className="banner warn small">Not run: {s.profile} ({s.evidence_mode}) – {s.reason}</div>
        ))}
        <h3>Shared reused artifacts</h3>
        <table className="tbl small">
          <thead><tr><th>Stage</th><th>Source run</th><th>Artifact</th><th>Hash</th><th>API call</th></tr></thead>
          <tbody>
            {rep.reused.filter((r) => !r.conditional).map((r) => (
              <tr key={r.artifact}><td>{r.title}</td><td className="mono">{r.source_run}</td><td className="mono">{r.artifact}</td>
                <td className="mono">{r.sha256.slice(0, 16)}…</td><td>No</td></tr>
            ))}
          </tbody>
        </table>
        <div className="small">
          Totals: tokens {rep.totals.tokens ? Object.entries(rep.totals.tokens).filter(([, v]) => v).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(", ") : "Not Available"}
          {" "}· Estimated Cost {rep.totals.estimated_cost_usd !== null ? fmtUsd(rep.totals.estimated_cost_usd) : "Not Available"}
          {rep.totals.cost_note ? ` (${rep.totals.cost_note})` : ""} · new map calls {rep.totals.new_map_calls} · new OSM calls {rep.totals.new_osm_calls}
        </div>
      </div>

      <ScrollX className="card">
        <table className="tbl small cmp">
          <thead>
            <tr>
              <th></th>
              {cols.map((c) => (
                <th key={c.run_id}>
                  <b>{c.profile}</b> <span className="tag">{c.evidence_mode}</span><br />
                  <button className="link mono" onClick={() => onOpenRun(c.run_id)}>{c.run_id}</button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {headerRows.map(([label, f]) => (
              <tr key={label}><th>{label}</th>{cols.map((c) => <td key={c.run_id}>{f(c)}</td>)}</tr>
            ))}
            {sections.map((sec) => (
              <Fragment key={sec}>
                <tr className="sec"><th colSpan={cols.length + 1}>{sec.replace("_", " ")}</th></tr>
                {rep.rows.filter((r) => r.section === sec).map((r) => (
                  <tr key={sec + r.field} className={r.differs ? "differs" : ""}>
                    <th className="mono">
                      {r.field}
                      {r.differs && <span className="tag">differs</span>}
                      {r.unknown_vs_resolved && <span className="tag">unknown vs resolved</span>}
                    </th>
                    {r.values.map((v, i) => (
                      <td key={i} className={`mono ${r.below_threshold?.[i] ? "below" : ""}`}>
                        {show(v)}{r.below_threshold?.[i] ? " ▼" : ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
        <div className="muted small">▼ = below the existing confidence threshold ({rep.confidence_threshold}). Highlighted rows differ between models.</div>
      </ScrollX>

      {rep.complete && <EvaluationPanel comparisonId={rep.comparison_id} />}

      {cols.map((c) => (
        <details key={c.run_id} className="card">
          <summary>{c.profile} – raw sanitized response and normalized observation</summary>
          <h4>Raw response (sanitized)</h4>
          <pre className="viewer">{c.raw_response ?? "Not available"}</pre>
          <h4>Normalized canonical observation</h4>
          <pre className="viewer">{c.observation ? JSON.stringify(c.observation, null, 2) : "None (model failed or not run)"}</pre>
        </details>
      ))}
    </>
  );
}
