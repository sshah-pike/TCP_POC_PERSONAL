import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import type { Json } from "./types";
import { Details, StateBadge, fmt } from "./parts";
import ReviewCard, { type Choice } from "./ReviewCard";
import { Icon } from "./icons";

// Message kinds stored by the backend -> user-facing chat types.
export const CHAT_TYPE: Record<string, string> = {
  SUMMARY: "PIPELINE_REQUEST", REVIEW_CARD: "PIPELINE_REQUEST", USER_TEXT: "SME_MESSAGE", INTERPRETATION: "AI_INTERPRETATION",
  STRUCTURED_FORM: "STRUCTURED_FORM", DETERMINISTIC_RESULT: "DETERMINISTIC_RESULT", CONFLICT_RESULT: "CONFLICT_RESULT",
  FINAL_REVIEW: "FINAL_REVIEW", CONFIRMATION: "CONFIRMATION", PIPELINE_STATUS: "PIPELINE_STATUS", VERSION_RESULT: "VERSION_RESULT",
  ERROR: "ERROR", TEXT: "PIPELINE_STATUS", COMMITTED: "CONFIRMATION",
};
const TYPE_META: Record<string, { label: string; icon: string }> = {
  PIPELINE_REQUEST: { label: "Pipeline", icon: "pipeline" }, SME_MESSAGE: { label: "You", icon: "user" },
  AI_INTERPRETATION: { label: "Interpretation", icon: "spark" }, STRUCTURED_FORM: { label: "Complete request", icon: "form" },
  DETERMINISTIC_RESULT: { label: "Calculated", icon: "calc" }, CONFLICT_RESULT: { label: "Needs decision", icon: "alert" },
  FINAL_REVIEW: { label: "Final review", icon: "review" }, CONFIRMATION: { label: "Confirmed", icon: "check" },
  PIPELINE_STATUS: { label: "Pipeline", icon: "pipeline" }, VERSION_RESULT: { label: "Version", icon: "layers" },
  ERROR: { label: "Error", icon: "alert" },
};

export interface ChatHandlers {
  act: (path: string, body?: Json) => Promise<Json>;
  onChooseFinding?: (f: Json) => (c: Choice, extra: Json) => void;
  onCreateObject?: (id: string) => void;
  onOpenFinalReview?: () => void;
  onOpenRun?: (id: string) => void;
  onChangeDistance?: (objectId: string) => void;
  canDecide: boolean;
}

// ---------------------------------------------------------------- inline structured form (no AI on submit)
export function InlineForm({ form, onSubmit, busy }: { form: Json; onSubmit: (values: Json) => void; busy?: boolean }) {
  const init: Json = {};
  for (const f of form.fields) if (f.default !== undefined && f.default !== null) init[f.name] = f.default;
  const [vals, setVals] = useState<Json>(init);
  const set = (k: string, v: unknown) => setVals({ ...vals, [k]: v });
  const missing = form.fields.filter((f: Json) => f.required && (vals[f.name] === undefined || vals[f.name] === ""));
  const known = Object.entries(form.known ?? {}).filter(([k]) => !["type", "action"].includes(k));
  return (
    <form className="sme-form" aria-label={form.title} onSubmit={(e) => { e.preventDefault(); if (!missing.length) onSubmit(vals); }}>
      <div className="sme-form-title"><Icon name="form" /> {form.title}</div>
      {known.length > 0 && (
        <dl className="sme-known">{known.map(([k, v]) => <div key={k}><dt>{k.replace(/_/g, " ")}</dt><dd>{fmt(v)}</dd></div>)}</dl>
      )}
      {form.fields.map((f: Json) => (
        <fieldset key={f.name} className="sme-field">
          <legend>{f.label}{f.required ? " *" : ""}</legend>
          {f.type === "choice" && (
            <div className="sme-segment" role="radiogroup" aria-label={f.label}>
              {f.options.map((o: Json) => (
                <label key={String(o.value)} className={vals[f.name] === o.value ? "on" : ""}>
                  <input type="radio" name={`${form.title}-${f.name}`} checked={vals[f.name] === o.value}
                         onChange={() => set(f.name, o.value)} />
                  <span>{o.label}</span>{o.hint && <small>{o.hint}</small>}
                </label>
              ))}
            </div>
          )}
          {f.type === "number" && (
            <input type="number" className="sme-input" aria-label={f.label} min={f.min} max={f.max} step="any"
                   value={vals[f.name] ?? ""} onChange={(e) => set(f.name, e.target.value === "" ? "" : Number(e.target.value))} />
          )}
          {f.type === "text" && (
            <input type="text" className="sme-input wide" aria-label={f.label} maxLength={f.max_length} placeholder={f.hint ?? ""}
                   value={vals[f.name] ?? ""} onChange={(e) => set(f.name, e.target.value)} />
          )}
        </fieldset>
      ))}
      {form.note && <div className="muted small">{form.note}</div>}
      <div className="sme-actions">
        <button type="submit" className="btn primary small" disabled={busy || missing.length > 0}>{form.submit_label}</button>
        <span className="muted small">No AI call on submit</span>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- deterministic placement result / conflict
export function PlacementResult({ b, h }: { b: Json; h: ChatHandlers }) {
  const [reason, setReason] = useState("");
  const [staged, setStaged] = useState(false);
  const conflict = b.plan_outcome === "BLOCKED" || (b.conflicts ?? []).some((c: Json) => c.severity === "BLOCKING");
  const stage = async (payload: Json) => { const r = await h.act("placements", { ...payload, reason }); if (r) setStaged(true); };
  const evalAt = (station: number, kind: string) =>
    h.act("placements/evaluate", { object_id: b.object_id, station_m: station, candidate_kind: kind });
  return (
    <div className={`sme-result ${conflict ? "conflict" : "ok"}`}>
      <div className="sme-result-head"><Icon name={conflict ? "alert" : "check"} /> <b>{b.title}</b></div>
      <div className="sme-grid2">
        <div><span className="k">Requested</span><span>{b.requested}</span></div>
        <div><span className="k">Calculated</span><span>{b.along_m} m along the road ({b.along_ft} ft) · straight {b.straight_m} m</span></div>
        <div><span className="k">Current station</span><span>{b.current_station_m} m</span></div>
        <div><span className="k">Proposed station</span><span>{b.proposed_station_m} m</span></div>
        <div><span className="k">Lateral offset</span><span>{b.offset_preserved ? "preserved" : "changed"} ({b.proposed?.offset_m} m)</span></div>
        <div><span className="k">Plan result</span><span>{b.plan_outcome}</span></div>
      </div>
      {(b.conflicts ?? []).length > 0 && (
        <ul className="sme-conflicts">
          {b.conflicts.map((c: Json, i: number) => (
            <li key={i} className={`sev-${c.severity}`}>
              <span className="sev">{c.severity === "BLOCKING" ? "Blocking" : c.severity === "WARNING" ? "Warning" : "Info"}</span>
              {c.relationship.replace(/_/g, " ").toLowerCase()} {c.type ? `- ${c.type.toLowerCase()}` : ""} {c.feature ?? ""}
              {c.source ? ` · ${c.source}` : ""}{c.confidence != null ? ` · conf ${c.confidence}` : ""}
              {c.overlap_m != null ? ` · overlap ${c.overlap_m} m` : ""}{c.distance_m != null ? ` · ${c.distance_m} m` : ""}
            </li>
          ))}
        </ul>
      )}
      {(b.rule_impact ?? []).length > 0 && (
        <div className="small">Rule results (unchanged validators): {b.rule_impact.map((r: Json) => `${r.check_id} ${r.current} → ${r.proposed}`).join(" · ")}</div>
      )}
      <div className="small">TA: {b.ta?.current_ta} {b.ta?.remains_applicable ? "remains applicable" : "would not apply"}
        {" "}· approved alternative TAs: {(b.ta?.candidate_tas ?? []).join(", ") || "none"}</div>
      {(b.candidates ?? []).length > 1 && (
        <div className="sme-candidates" role="group" aria-label="Candidate positions">
          {b.candidates.map((c: Json) => (
            <button key={c.kind} type="button" className="chip" disabled={!h.canDecide} onClick={() =>
              c.kind === "ORIGINAL" ? h.act("placements/keep", { object_id: b.object_id }) : evalAt(c.station_m, c.kind)}>
              {c.kind === "ORIGINAL" ? "Keep current position" : `${c.label} · ${c.station_m} m`}
            </button>
          ))}
          <div className="muted small">{b.candidates[0]?.note ?? "POC candidates based on saved approximate site geometry. SME verification required."} Never applied automatically.</div>
        </div>
      )}
      {h.canDecide && !staged && (
        <div className="sme-actions">
          <input className="sme-input wide" aria-label="Engineering reason" placeholder="Engineering reason (required to stage)"
                 value={reason} onChange={(e) => setReason(e.target.value)} />
          <button type="button" className="btn primary small" disabled={!reason.trim()} onClick={() => stage(b.stage_payload)}>
            {conflict ? "Stage anyway (decide exceptions in review)" : "Stage this movement"}</button>
          {h.onChangeDistance && <button type="button" className="btn small" onClick={() => h.onChangeDistance!(b.object_id)}>Choose a different distance</button>}
        </div>
      )}
      {staged && <div className="sme-note ok"><Icon name="check" /> Staged (not committed). Review the change set before confirming.</div>}
      <Details title="Technical details (level 3)"><pre className="viewer short">{JSON.stringify(b.evaluation?.movement ?? b, null, 1)}</pre></Details>
    </div>
  );
}

// ---------------------------------------------------------------- AI interpretation (never applied by the model)
function Interpretation({ b, h }: { b: Json; h: ChatHandlers }) {
  const [reason, setReason] = useState("");
  if (["REJECTED_SECURITY", "REJECTED_HARMFUL", "OUT_OF_SCOPE"].includes(b.status))
    return <div className="sme-note warn"><Icon name="shield" /> {b.message}</div>;
  if (b.status === "ANSWERED") return <div className="sme-note info"><Icon name="info" /> {b.message}<div className="muted small">Answered from saved data (no AI call).</div></div>;
  if (b.status === "REJECTED_OUTPUT" || b.status === "MODEL_UNAVAILABLE")
    return <div className="sme-note bad"><Icon name="alert" /> The request could not be interpreted ({b.error?.code}). Use the guided controls. Nothing was changed.</div>;
  const it = b.interpretation ?? {};
  const run = async (o: Json) => {
    const s = o.structured;
    if (s.route === "objects") return h.onCreateObject?.(s.payload.object_id ?? "");
    if (s.route === "placements") return h.act("placements/evaluate", { ...s.payload, message_id: b.message_id });
    if (s.route === "placements/relative") return h.act("placements/relative", { ...s.payload, message_id: b.message_id });
    return h.act(s.route === "decisions" ? "decisions" : s.route, { ...s.payload, reason, message_id: b.message_id });
  };
  return (
    <div className="sme-interp">
      <div className="muted small">Understood as <b>{(it.intent ?? "").replace(/_/g, " ").toLowerCase()}</b>
        {it.interpretation_confidence != null && <> · confidence {Math.round(it.interpretation_confidence * 100)}%</>} · nothing applied yet</div>
      {(b.operations ?? []).map((o: Json, i: number) => (
        <div key={i} className="sme-op">
          <div className="sme-op-head">
            <span className={`pill-s ${o.status === "READY" ? "ok" : o.status === "REJECTED" ? "bad" : "warn"}`}>
              {o.status === "READY" ? "Ready" : o.status === "REJECTED" ? "Not possible" : "Needs information"}</span>
            <b>{o.op.operation.replace(/_/g, " ").toLowerCase()}</b> {o.resolution?.resolved_entity_id ?? o.op.target_id}
            {o.resolution?.resolution_method === "CASE_INSENSITIVE" && <span className="muted small"> (you wrote “{o.resolution.original_reference}”)</span>}
          </div>
          {o.reason && <div className="small bad-text">{o.reason}</div>}
          {o.explanation && <div className="small">{o.explanation}</div>}
          {o.assumption && <div className="muted small">Assumption: {o.assumption}</div>}
          {o.form && h.canDecide && (
            <InlineForm form={o.form} onSubmit={async (values) => {
              const r = await h.act("forms/submit", { interpretation_id: b.interpretation_id, op_index: i, values });
              if (r?.open_object_form) h.onCreateObject?.(r.open_object_form);
            }} />
          )}
          {!o.form && o.clarification && <div className="small">{o.clarification.message}</div>}
          {o.status === "READY" && o.structured && o.structured.route !== "explain" && h.canDecide && (
            <div className="sme-actions">
              {o.structured.route === "decisions" && <input className="sme-input wide" aria-label="Reason" placeholder="Reason"
                                                            value={reason} onChange={(e) => setReason(e.target.value)} />}
              <button type="button" className="btn primary small" onClick={() => run(o)}>
                {o.structured.route.startsWith("placements") ? "Validate proposed movement" : "Stage this change"}</button>
            </div>
          )}
        </div>
      ))}
      <Details title="Technical details (level 3)"><pre className="viewer short">{JSON.stringify({ interpretation_id: b.interpretation_id, message_id: b.message_id, interpretation: it }, null, 1)}</pre></Details>
    </div>
  );
}

// ---------------------------------------------------------------- one chat message
function Bubble({ m, findings, staged, h }: { m: Json; findings: Record<string, Json>; staged: Json[]; h: ChatHandlers }) {
  const type = CHAT_TYPE[m.kind] ?? "PIPELINE_STATUS";
  const meta = TYPE_META[type];
  const b = m.body ?? {};
  let content: ReactNode = null;
  if (m.kind === "SUMMARY") content = <div><b>{b.title}</b><div>{b.text}</div></div>;
  else if (m.kind === "REVIEW_CARD") {
    const f = findings[b.finding_id];
    content = f ? <ReviewCard f={f} onChoose={h.canDecide && h.onChooseFinding ? h.onChooseFinding(f) : undefined}
                              staged={staged.find((s: Json) => s.finding_id === b.finding_id)} />
                : <div className="muted small">Finding {b.finding_id} is resolved in the current version.</div>;
  }
  else if (m.kind === "USER_TEXT") content = <div className="sme-user-text">{m.text}</div>;
  else if (m.kind === "INTERPRETATION") content = <Interpretation b={{ ...b, message_id: b.message_id }} h={h} />;
  else if (m.kind === "CONFLICT_RESULT" || (m.kind === "DETERMINISTIC_RESULT" && b.stage_payload)) content = <PlacementResult b={b} h={h} />;
  else if (m.kind === "FINAL_REVIEW") content = (
    <div><b>{b.title}</b> <span className={`pill-s ${b.blocked ? "bad" : "ok"}`}>{b.blocked ? "Blocked" : "Ready to confirm"}</span>
      <div className="small">{b.text}</div>
      {h.onOpenFinalReview && <button type="button" className="btn small" onClick={h.onOpenFinalReview}>Open final review</button>}</div>);
  else if (m.kind === "PIPELINE_STATUS" && b.run_id) content = (
    <div><b>{b.title}</b> {b.status && <span className="pill-s">{b.status}</span>}<div className="small">{b.text}</div>
      {h.onOpenRun && <button type="button" className="link mono" onClick={() => h.onOpenRun!(b.run_id)}>{b.run_id}</button>}</div>);
  else if (m.kind === "VERSION_RESULT") content = (
    <div><b>{b.title}</b><div className="small">{[b.site_evidence_version && `site evidence ${b.site_evidence_version}`,
      b.plan_version_id && `plan ${b.plan_version_id}`, b.status].filter(Boolean).join(" · ")}</div></div>);
  else content = <div>{b.title && <b>{b.title} </b>}<span>{b.text ?? m.text ?? ""}</span></div>;
  return (
    <li className={`sme-bubble t-${type} r-${m.role}`} data-type={type}>
      <div className="sme-bubble-meta"><Icon name={meta.icon} /> {meta.label}
        <time dateTime={m.created_at}>{new Date(m.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time></div>
      {content}
    </li>
  );
}

// ---------------------------------------------------------------- the flow (scroll preservation + live region)
export default function ChatFlow({ messages, findings, staged, h, blockingAnnouncement, fill, children }: {
  messages: Json[]; findings: Json[]; staged: Json[]; h: ChatHandlers; blockingAnnouncement?: string;
  fill?: boolean;            // chat-only window: the conversation is the ONLY scrolling region and fills the panel
  children?: ReactNode;      // extra flow content shown at the end of the conversation (forms, final review)
}) {
  const box = useRef<HTMLDivElement>(null);
  const [atBottom, setAtBottom] = useState(true);
  const [unseen, setUnseen] = useState(0);
  const prevLen = useRef(messages.length);
  const byId = Object.fromEntries(findings.map((f) => [f.finding_id, f]));
  const onScroll = () => {
    const el = box.current; if (!el) return;
    const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    setAtBottom(bottom); if (bottom) setUnseen(0);
  };
  useLayoutEffect(() => {   // follow new messages only if the SME is already at the bottom (never force-scroll)
    const el = box.current; const added = messages.length - prevLen.current; prevLen.current = messages.length;
    if (!el || added <= 0) return;
    if (atBottom) el.scrollTop = el.scrollHeight; else setUnseen((u) => u + added);
  }, [messages.length, !!children]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { const el = box.current; if (el) el.scrollTop = el.scrollHeight; }, []);
  const toLatest = () => { const el = box.current; if (el) el.scrollTop = el.scrollHeight; setUnseen(0); setAtBottom(true); };
  return (
    <div className={`sme-chatwrap ${fill ? "fill" : ""}`}>
      <div className="sr-only" role="status" aria-live="assertive">{blockingAnnouncement}</div>
      <div className="sme-chatbox" ref={box} onScroll={onScroll} tabIndex={0} aria-label="Review conversation">
        <ol className="sme-chatlist">
          {messages.map((m) => <Bubble key={m.message_id} m={m} findings={byId} staged={staged} h={h} />)}
        </ol>
        {children}
      </div>
      {!atBottom && (
        <button type="button" className="sme-latest" onClick={toLatest}>
          <Icon name="down" /> Scroll to latest{unseen > 0 ? ` (${unseen} new)` : ""}</button>
      )}
    </div>
  );
}

export { StateBadge };
