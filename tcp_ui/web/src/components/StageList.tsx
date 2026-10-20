import { useState } from "react";
import { fmtMs, fmtTime, STATUS_ICON, STATUS_LABEL } from "../format";
import type { Span, Stage } from "../types";
import ArtifactLink from "./ArtifactLink";

interface Props {
  runId: string;
  stages: Stage[];
  now: number;
  sizes: Record<string, number>;
  onResume?: (stage: string, title: string) => void;
  resumableStages?: string[];
}

const RESUMABLE = new Set(["COMPLETED", "WARNING", "REVIEW", "ERROR", "FAILED", "UNSUPPORTED"]);

function headline(s: Stage): string {
  if (s.status === "WAITING") return "Waiting";
  if (s.status === "NOT_RUN") return "Not run – pipeline stopped before this stage";
  if (s.status === "RUNNING") {  // live: what this stage announced so far (e.g. AI provider / model, current call)
    if (s.messages.length === 0) return "Running…";
    const last = s.messages[s.messages.length - 1];
    return `Running… ${s.messages[0]}${s.messages.length > 1 ? ` · ${last}` : ""}`;
  }
  return s.messages[0] ?? STATUS_LABEL[s.status];
}

const AGENT_STEPS: { key: string; title: string; hint: string }[] = [
  { key: "call1", title: "Call 1", hint: "wide image, blind to OSM" },
  { key: "compare", title: "Compare", hint: "after call 1: deterministic, OSM + geometry" },
  { key: "measure", title: "Measure", hint: "close map views, cross-section measurement (no model call)" },
  { key: "recompare", title: "Re-compare", hint: "after measurement: what is still unresolved" },
  { key: "crops", title: "Crops", hint: "close views for unresolved fields" },
  { key: "call2", title: "Call 2", hint: "crops + wide image + OSM claims" },
  { key: "consistency", title: "Consistency", hint: "call 1 vs call 2" },
];

function stepDetail(a: Record<string, unknown>): string {
  const bits: string[] = [];
  if (a.reason) bits.push(String(a.reason));
  if (a.model) bits.push(String(a.model));
  if (a.views_sent !== undefined) bits.push(`${a.views_sent} image${a.views_sent === 1 ? "" : "s"}`);
  if (a.fields) bits.push(`fields: ${a.fields}`);
  if (a.unresolved) bits.push(`unresolved: ${a.unresolved}`);
  if (a.images !== undefined && a.crops === undefined) bits.push(`${a.images} image${a.images === 1 ? "" : "s"}`);
  if (a.map_requests !== undefined) bits.push(`${a.map_requests} map API request${a.map_requests === 1 ? "" : "s"}`);
  if (a.reused_views) bits.push(`${a.reused_views} retrieved from cache (no API call)`);
  if (a.sources) bits.push(String(a.sources));
  if (a.width !== undefined && a.width !== null) bits.push(`width ${a.width} m, centre offset ${a.centre_offset} m`);
  if (a.crops !== undefined) bits.push(`${a.crops} crop(s), zoom ${a.zooms || "–"}`);
  if (a.mismatches) bits.push(`mismatch: ${a.mismatches}`);
  if (a.usage_in) bits.push(`${a.usage_in} in / ${a.usage_out} out tokens`);
  if (a.error_code) bits.push(String(a.error_code));
  return bits.join(" · ");
}

/** Live tracker of the agent's model calls and the deterministic steps between them. */
function AgentSteps({ steps, running, now }: { steps: Span[]; running: boolean; now: number }) {
  const by = new Map(steps.map((s) => [s.name.replace("tcp.agent.", ""), s]));
  return (
    <div className="steps">
      {AGENT_STEPS.map((st, i) => {
        const sp = by.get(st.key);
        const outcome = String(sp?.attributes.outcome ?? "");
        const state = !sp ? (running ? "pending" : "none") : sp.ended_at === null ? "active"
          : outcome === "SKIPPED" ? "skipped" : ["ERROR", "NOT_MADE", "NONE_AVAILABLE"].includes(outcome) ? "error"
          : ["UNRESOLVED", "MISMATCH", "INCONCLUSIVE"].includes(outcome) ? "attention" : "done";
        const dur = sp ? (sp.ended_at === null ? now - Date.parse(sp.started_at) : sp.duration_ms) : null;
        return (
          <div key={st.key} className={`step step-${state}`} title={st.hint}>
            <div className="step-dot">{state === "active" ? <span className="spin">◌</span> : state === "done" ? "✓" : state === "skipped" ? "–" : state === "error" ? "✕" : state === "attention" ? "!" : i + 1}</div>
            <div className="step-text">
              <div className="step-title">{st.title}{sp && <span className="step-dur mono">{fmtMs(dur)}</span>}</div>
              <div className={`step-sub ${sp ? "outcome" : ""}`}>{sp ? (state === "active" ? "running…" : outcome.toLowerCase().replace(/_/g, " ")) : st.hint}</div>
              {sp && <div className="step-detail">{stepDetail(sp.attributes)}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StageRow({ runId, stage: s, now, sizes, onResume, resumable }: { runId: string; stage: Stage; now: number; sizes: Record<string, number>; onResume?: Props["onResume"]; resumable: boolean }) {
  const [open, setOpen] = useState(false);
  const live = s.status === "RUNNING" && s.started_at ? now - Date.parse(s.started_at) : null;
  const expandable = s.status !== "WAITING" && s.status !== "NOT_RUN";
  return (
    <div className={`stage st-${s.status.toLowerCase()}`}>
      <button type="button" className="stage-head" onClick={() => expandable && setOpen(!open)} disabled={!expandable}>
        <span className={`icon ${s.status === "RUNNING" ? "spin" : ""}`}>{STATUS_ICON[s.status]}</span>
        <span className="stage-title">
          {s.index}. {s.title}
          {s.reuse.length > 0 && <span className="tag reused">REUSED</span>}
        </span>
        <span className="stage-line">{headline(s)}</span>
        <span className="stage-status">{STATUS_LABEL[s.status]}</span>
        <span className="stage-dur mono">{live !== null ? fmtMs(live) : fmtMs(s.duration_ms)}</span>
      </button>
      {s.key === "vision" && (s.steps?.length ?? 0) > 0 && <AgentSteps steps={s.steps!} running={s.status === "RUNNING"} now={now} />}
      {open && (
        <div className="stage-body">
          <div className="kv">
            <span>Started</span>
            <span>{fmtTime(s.started_at)}</span>
            <span>Completed</span>
            <span>{fmtTime(s.ended_at)}</span>
            <span>Duration</span>
            <span>{fmtMs(s.duration_ms)} (from pipeline telemetry spans)</span>
          </div>
          {s.reuse.map((r) => (
            <div key={r.kind + r.artifact_id} className="banner info small">
              <b>REUSED</b> · Source run: <span className="mono">{r.source_run}</span> · API call made: <b>No</b> · Artifact:{" "}
              <span className="mono">{r.artifact_id}</span> · Artifact hash: <span className="mono">{r.sha256}</span>
            </div>
          ))}
          {s.reuse_rejected.map((r, i) => (
            <div key={i} className="banner warn small">
              Not reused from <span className="mono">{r.source_run}</span>: {r.reason} – re-acquired (new call)
            </div>
          ))}
          {s.new_calls.length > 0 && (
            <div className="small">
              New external calls ({s.new_calls.length}, {s.new_calls.reduce((n, c) => n + c.requests, 0)} requests):
              {s.new_calls.map((c, i) => (
                <div key={i} className="mono">
                  {i + 1}. {c.service} · {c.provider} · {c.requests} request{c.requests === 1 ? "" : "s"}{c.purpose ? " · " + c.purpose : ""} · {fmtMs(c.duration_ms)}
                </div>
              ))}
            </div>
          )}
          {onResume && resumable && RESUMABLE.has(s.status) && (
            <div className="buttons">
              <button className="btn" onClick={() => onResume(s.key, s.title)}>Re-run from this step…</button>
            </div>
          )}
          {s.problems.length > 0 && (
            <div className="banner warn small">
              {s.problems.map((p) => (
                <div key={p} className="mono">
                  {p}
                </div>
              ))}
            </div>
          )}
          {s.diagnostics.map((d, i) => (
            <div key={i} className="diag">
              <h4>Pipeline result</h4>
              <div className="kv">
                <span>Error code</span>
                <span className="mono">{d.pipeline_error_code ?? "—"}</span>
              </div>
              <h4>Technical diagnostic</h4>
              <div className="kv">
                <span>Provider</span>
                <span className="mono">{d.provider ?? "—"}</span>
                <span>Category</span>
                <span className="mono">
                  <b>{d.category}</b>
                </span>
                <span>Exception</span>
                <span className="mono">{d.exception_type}</span>
                <span>Message</span>
                <span className="mono">{d.message}</span>
                {d.http_status !== null && (
                  <>
                    <span>HTTP status</span>
                    <span className="mono">{d.http_status}</span>
                  </>
                )}
                <span>Request duration</span>
                <span className="mono">{fmtMs(d.duration_ms)}</span>
              </div>
            </div>
          ))}
          {s.messages.length > 0 && (
            <>
              <h4>Pipeline output</h4>
              <pre className="viewer short">{s.messages.join("\n")}</pre>
            </>
          )}
          <h4>Telemetry spans</h4>
          <table className="tbl small">
            <thead>
              <tr>
                <th>Span</th>
                <th>Status</th>
                <th>Duration</th>
                <th>Attributes</th>
              </tr>
            </thead>
            <tbody>
              {s.spans.map((sp) => (
                <tr key={sp.name + sp.started_at}>
                  <td className="mono">{sp.name}</td>
                  <td>{sp.status ?? "running"}</td>
                  <td className="mono">{fmtMs(sp.duration_ms)}</td>
                  <td className="mono">
                    {Object.entries(sp.attributes)
                      .map(([k, v]) => `${k}=${v === null ? "null" : String(v)}`)
                      .join("  ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {s.artifacts.length > 0 && (
            <>
              <h4>Artifacts</h4>
              {s.artifacts.map((a) => (
                <ArtifactLink key={a} runId={runId} name={a} size={sizes[a]} />
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function StageList({ runId, stages, now, sizes, onResume, resumableStages }: Props) {
  return (
    <div className="stages">
      {stages.map((s) => (
        <StageRow key={s.key} runId={runId} stage={s} now={now} sizes={sizes} onResume={onResume}
                  resumable={!resumableStages || resumableStages.includes(s.key)} />
      ))}
    </div>
  );
}
