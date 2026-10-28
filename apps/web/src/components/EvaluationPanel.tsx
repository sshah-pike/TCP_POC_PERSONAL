import { useEffect, useState } from "react";
import { getEvaluation } from "../api";
import { fmtMs, fmtUsd } from "../format";
import type { Evaluation } from "../types";
import ScrollX from "./ScrollX";

const show = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
const OUTCOME_CLASS: Record<string, string> = { CORRECT: "ok", FALSE_RESOLUTION: "bad", UNRESOLVED: "warn", NO_LABEL: "" };

/** Per-field predicted value vs the human label. Primary safety metric: FALSE_RESOLUTION. No ranking. */
export default function EvaluationPanel({ comparisonId }: { comparisonId: string }) {
  const [ev, setEv] = useState<Evaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { getEvaluation(comparisonId).then(setEv).catch((e: Error) => setError(e.message)); }, [comparisonId]);
  if (error) return <div className="card">Evaluation unavailable: {error}</div>;
  if (!ev) return <div className="card">Loading evaluation…</div>;
  return (
    <ScrollX className="card">
      <h2>Evaluation against human label</h2>
      <div className={`banner ${ev.scored ? "info" : "warn"} small`}>
        {ev.label ? <>Label {ev.label.site_id}: <b>{ev.label.status}</b>
          {ev.label.status === "CONFIRMED" ? ` by ${ev.label.confirmed_by} (${ev.label.confirmed_at}) – ${ev.label.confirm_reason}` : ` (drafted by ${ev.label.drafted_by})`}</>
          : "No label for this site."} {ev.note}
      </div>
      <table className="tbl small cmp">
        <thead>
          <tr><th>Run</th><th>False resolution</th><th>Correct</th><th>Unresolved</th><th>No label</th><th>AI time</th><th>Tokens in/out</th><th>Estimated cost</th><th>Checks</th></tr>
        </thead>
        <tbody>
          {ev.columns.map((c) => (
            <tr key={c.run_id}>
              <th>{c.label}</th>
              <td className="mono below">{c.counts.FALSE_RESOLUTION}</td><td className="mono">{c.counts.CORRECT}</td>
              <td className="mono">{c.counts.UNRESOLVED}</td><td className="mono">{c.counts.NO_LABEL}</td>
              <td className="mono">{fmtMs(c.ai_duration_ms)}</td>
              <td className="mono">{c.usage ? `${c.usage.input_tokens ?? "?"} / ${c.usage.output_tokens ?? "?"}` : "Not Available"}</td>
              <td>{c.estimated_cost_usd !== null ? fmtUsd(c.estimated_cost_usd) : "Not Available"}</td>
              <td className="mono">{(c.checks ?? []).map((k) => `${k.id.split("_")[0]}:${k.result}`).join(" ") || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {ev.columns.map((c) => (
        <details key={c.run_id}>
          <summary>{c.label} – per-field detail ({c.decision ?? "—"}, {c.model ?? "model n/a"})</summary>
          <table className="tbl small">
            <thead><tr><th>Field</th><th>Predicted</th><th>Status</th><th>Conf.</th><th>Label</th><th>Outcome</th><th>Evidence statement</th><th>Check</th></tr></thead>
            <tbody>
              {c.rows.map((r) => (
                <tr key={r.field}>
                  <td className="mono">{r.field}</td><td className="mono">{show(r.predicted)}</td><td>{r.status}</td>
                  <td className="mono">{r.confidence ?? "—"}</td><td className="mono">{show(r.label)}</td>
                  <td><span className={`pill ${OUTCOME_CLASS[r.outcome] ?? ""}`}>{r.outcome}{r.scored ? "" : " (not scored)"}</span></td>
                  <td className="small">{r.evidence ? `[${r.evidence_image}] ${r.evidence}` : "—"}</td>
                  <td className="mono">{r.check ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ))}
    </ScrollX>
  );
}
