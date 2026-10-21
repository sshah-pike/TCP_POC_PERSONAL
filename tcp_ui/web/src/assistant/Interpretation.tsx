import { useState } from "react";
import * as A from "./api";
import type { Json } from "./types";
import { Details, KV } from "./parts";

// Optional natural-language input: ONE bounded interpretation call; nothing is staged by the model.
export function MessageComposer({ cid, onResult }: { cid: string; onResult: () => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const send = async () => {
    setBusy(true); setErr(null);
    try { await A.post(`conversations/${cid}/messages`, { text }); setText(""); onResult(); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="sme-composer">
      <textarea rows={2} maxLength={2000} placeholder="Optional: describe a draft change (e.g. “Move S2 100 ft upstream”). Uses one AI interpretation call; structured buttons above use none."
                value={text} onChange={(e) => setText(e.target.value)} />
      <button className="btn" disabled={busy || !text.trim()} onClick={send}>{busy ? "Interpreting…" : "Interpret"}</button>
      {err && <div className="banner bad small">{err}</div>}
    </div>
  );
}

// Interpretation preview with deterministic clarification and structured apply buttons.
export function InterpretationCard({ cid, body, onApplied, onCreateObject }: {
  cid: string; body: Json; onApplied: (r: Json) => void; onCreateObject: (id: string) => void;
}) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [evals, setEvals] = useState<Record<number, Json>>({});
  const mid = body.message_id;
  const apply = async (i: number, s: Json) => {
    setErr(null);
    try {
      const p = { ...s.payload, reason, message_id: mid };
      if (s.route === "decisions") onApplied(await A.post(`conversations/${cid}/decisions`, p));
      else if (s.route === "placements") setEvals({ ...evals, [i]: (await A.post<Json>(`conversations/${cid}/placements/evaluate`, p)).evaluation });
      else if (s.route === "placements/relative") setEvals({ ...evals, [i]: (await A.post<Json>(`conversations/${cid}/placements/relative`, p)).evaluation });
      else if (s.route === "objects/remove") onApplied(await A.post(`conversations/${cid}/objects/remove`, p));
      else if (s.route === "objects") onCreateObject(s.payload.object_id || "");
    } catch (e) { setErr((e as Error).message); }
  };
  const stageMove = async (i: number, s: Json) => {
    const ev = evals[i]; const p = { object_id: ev.movement.object_id, station_m: ev.movement.proposed.station_m, reason, message_id: mid };
    try { onApplied(await A.post(`conversations/${cid}/placements`, s.route === "placements" ? { ...s.payload, reason, message_id: mid } : p)); }
    catch (e) { setErr((e as Error).message); }
  };
  if (["REJECTED_SECURITY", "REJECTED_HARMFUL", "OUT_OF_SCOPE"].includes(body.status))
    return <div className="banner warn small">{body.message}</div>;
  if (body.status === "REJECTED_OUTPUT" || body.status === "MODEL_UNAVAILABLE")
    return <div className="banner bad small">The request could not be interpreted safely ({body.error?.code}). Use the structured controls. Nothing was changed.</div>;
  const it = body.interpretation ?? {};
  return (
    <div className="sme-interp">
      <b>AI interpretation (not applied)</b> — status {body.status}
      <KV rows={[["Intent", it.intent], ["Confidence", it.interpretation_confidence], ["Assumptions", (it.assumptions ?? []).join("; ")],
                 ["Ambiguities", (it.ambiguities ?? []).join("; ")], ["Missing information", (it.missing_information ?? []).join("; ")]]} />
      {(body.operations ?? []).map((o: Json, i: number) => (
        <div key={i} className="sme-card">
          <div><b>{o.op.operation}</b> {o.op.target_id} {o.op.direction !== "NONE" ? o.op.direction : ""} {o.op.distance || ""} {o.op.unit !== "NONE" ? o.op.unit : ""} — {o.status}</div>
          {o.assumption && <div className="small muted">Assumption: {o.assumption}</div>}
          {o.reason && <div className="small bad-text">{o.reason}</div>}
          {o.explanation && <div className="small">{o.explanation}</div>}
          {o.clarification && (
            <div className="small">{o.clarification.message}
              <div className="buttons">{o.clarification.buttons.map((b: Json, j: number) => (
                <button key={j} className="btn small" onClick={() => {
                  if (b.create_object_id !== undefined) return onCreateObject(b.create_object_id);
                  if (b.open_object_form) return onCreateObject(o.structured?.payload?.object_id ?? "");
                  if (b.target_id && o.structured === null && o.op.operation === "MOVE_DEVICE")
                    return apply(i, { route: "placements", payload: { object_id: b.target_id, direction: o.op.direction, distance: o.op.distance, unit: o.op.unit, preserve_lateral_offset: o.op.preserve_lateral_offset !== "NO" } });
                }}>{b.label}</button>))}</div>
            </div>
          )}
          {o.status === "READY" && o.structured && o.structured.route !== "explain" && (
            <button className="btn small" onClick={() => apply(i, o.structured)}>
              {o.structured.route.startsWith("placements") ? "Evaluate (deterministic)" : "Apply as staged change (deterministic)"}</button>
          )}
          {evals[i] && (
            <div className="small">
              Calculated: {evals[i].movement.actual_along_alignment_m} m along the alignment; plan result {evals[i].plan_outcome.status};
              blocking: {evals[i].blocking.map((x: Json) => `${x.relationship} ${x.feature?.type ?? ""}`).join(", ") || "none"}
              <button className="btn small" disabled={!reason.trim()} onClick={() => stageMove(i, o.structured)}>Stage this move</button>
            </div>
          )}
        </div>
      ))}
      <input className="sme-input wide" placeholder="reason (required to stage)" value={reason} onChange={(e) => setReason(e.target.value)} />
      {err && <div className="banner bad small">{err}</div>}
      <Details title="Technical (level 3)"><pre className="viewer short">{JSON.stringify({ message_id: mid, interpretation: it }, null, 1)}</pre></Details>
    </div>
  );
}
