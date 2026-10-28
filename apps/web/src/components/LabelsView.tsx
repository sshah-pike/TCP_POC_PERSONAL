import { useEffect, useState } from "react";
import { confirmLabel, evidenceUrl, listLabels, revokeLabel } from "../api";
import type { Label } from "../types";

/** Human ground truth: a person reviews a draft label against the evidence and confirms it (name + reason). */
export default function LabelsView() {
  const [items, setItems] = useState<Label[]>([]);
  const [error, setError] = useState<string | null>(null);
  const refresh = () => listLabels().then(setItems).catch((e: Error) => setError(e.message));
  useEffect(() => { refresh(); }, []);
  return (
    <>
      <div className="card">
        <h2>Evaluation labels</h2>
        <div className="muted small">Only CONFIRMED labels count as ground truth. Drafts (for example prepared by an assistant from
          the evidence) must be checked and confirmed by a person; reviewer, reason and timestamp are recorded.</div>
        {error && <div className="banner bad small">{error}</div>}
        {items.length === 0 && <div className="muted small">No labels yet.</div>}
      </div>
      {items.map((l) => <LabelCard key={l.site_id} label={l} onChange={refresh} />)}
    </>
  );
}

function LabelCard({ label, onChange }: { label: Label; onChange: () => void }) {
  const [reviewer, setReviewer] = useState("");
  const [reason, setReason] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const parse = (field: string, raw: string): unknown => {
    const cur = label.fields[field]?.value;
    if (raw === "") return cur;
    if (typeof cur === "boolean" || raw === "true" || raw === "false") return raw === "true";
    if (typeof cur === "number") return Number(raw);
    return raw;
  };
  async function act(kind: "confirm" | "revoke") {
    setMsg(null);
    try {
      if (kind === "confirm") {
        const e: Record<string, unknown> = {};
        for (const [k, v] of Object.entries(edits)) if (v !== "") e[k] = parse(k, v);
        await confirmLabel(label.site_id, reviewer, reason, e);
      } else await revokeLabel(label.site_id, reviewer, reason);
      setEdits({}); onChange();
    } catch (err) { setMsg((err as Error).message); }
  }
  return (
    <div className="card">
      <div className="runhead">
        <h2>{label.name ?? "Site"} <span className="mono">{label.site_id}</span></h2>
        <span className={`pill ${label.status === "CONFIRMED" ? "ok" : "warn"}`}>{label.status}</span>
      </div>
      <div className="muted small">
        Work reference {label.work_reference.latitude.toFixed(6)}, {label.work_reference.longitude.toFixed(6)} · source run {label.source_run_id} ·
        drafted by {label.drafted_by} ({label.drafted_at})
        {label.status === "CONFIRMED" && <> · confirmed by <b>{label.confirmed_by}</b> ({label.confirmed_at}): {label.confirm_reason}</>}
      </div>
      <table className="tbl small">
        <thead><tr><th>Field</th><th>Value</th><th>Tolerance</th><th>Note</th><th>Evidence</th>{label.status === "DRAFT" && <th>Correct to</th>}</tr></thead>
        <tbody>
          {Object.entries(label.fields).map(([k, f]) => (
            <tr key={k}>
              <td className="mono">{k}</td><td className="mono">{String(f.value)}</td><td className="mono">{f.tolerance ?? "—"}</td>
              <td className="small">{f.note ?? ""}</td>
              <td className="small">{f.evidence.map((e) => (
                e.file ? <a key={e.artifact} className="link" href={evidenceUrl(e.run, e.file)} target="_blank" rel="noreferrer">{e.artifact} </a>
                  : <span key={e.artifact} className="mono">{e.artifact} </span>))}</td>
              {label.status === "DRAFT" && (
                <td><input placeholder="(keep)" value={edits[k] ?? ""} onChange={(ev) => setEdits({ ...edits, [k]: ev.target.value })} /></td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row2">
        <div className="field"><label className="label">Reviewer (your name)</label>
          <input value={reviewer} onChange={(e) => setReviewer(e.target.value)} /></div>
        <div className="field"><label className="label">Reason / basis</label>
          <input value={reason} onChange={(e) => setReason(e.target.value)} /></div>
      </div>
      {msg && <div className="banner bad small">{msg}</div>}
      <div className="buttons">
        {label.status === "DRAFT" ? (
          <button className="primary inline" disabled={!reviewer.trim() || !reason.trim()} onClick={() => act("confirm")}>Confirm as ground truth</button>
        ) : (
          <button className="btn" disabled={!reviewer.trim() || !reason.trim()} onClick={() => act("revoke")}>Revoke confirmation</button>
        )}
      </div>
      <details><summary className="small">History</summary>
        <pre className="viewer short">{label.history.map((h) => `${h.at}  ${h.action}  ${h.by}  – ${h.reason}`).join("\n")}</pre>
      </details>
    </div>
  );
}
