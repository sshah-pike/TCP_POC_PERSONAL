import { useState } from "react";
import type { Json } from "./types";
import { KV } from "./parts";

// Plan-specific SME engineering exception. Deterministic; self-confirmed in this POC (not independent approval).
export default function ExceptionDialog({ kind, row, ta, onSubmit, onCancel }: {
  kind: "RULE_CONFLICT" | "TA_NOT_APPLICABLE"; row?: Json; ta?: Json; onSubmit: (p: Json) => void; onCancel: () => void;
}) {
  const [reason, setReason] = useState("");
  const [ok, setOk] = useState(false);
  return (
    <div className="card sme-exception">
      <h4>{kind === "RULE_CONFLICT" ? `SME exception for validator ${row?.check_id}` : "Proceed without an applicable TA (SME exception)"}</h4>
      {kind === "RULE_CONFLICT" ? (
        <KV rows={[["Rule", row?.rule_id], ["Current validator result", row?.current], ["Proposed validator result", row?.proposed],
                   ["Rule status after exception", "CONFLICT (unchanged — not compliant)"],
                   ["Disposition if confirmed", "ACCEPTED_WITH_SME_OVERRIDE"], ["Plan status", "DRAFT_WITH_ENGINEERING_EXCEPTION"],
                   ["Scope", "THIS_PLAN_VERSION_ONLY"], ["Detail", JSON.stringify(row?.detail_proposed ?? null)]]} />
      ) : (
        <KV rows={[["Current TA", ta?.current?.ta_id], ["Result", ta?.proposed?.message],
                   ["Failed conditions", (ta?.proposed?.reason_codes ?? []).join(", ")],
                   ["Approved alternatives", "none — no other TA will be selected"], ["Plan status", "DRAFT_WITH_ENGINEERING_EXCEPTION"]]} />
      )}
      <input className="sme-input wide" placeholder="engineering reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <label className="small"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> I confirm this plan-specific
        engineering exception (self-confirmed POC; not an independent approval; the rule result stays CONFLICT).</label>
      <div className="buttons">
        <button className="btn" onClick={onCancel}>Cancel</button>
        <button className="btn primary" disabled={!ok || !reason.trim()}
                onClick={() => onSubmit({ type: kind, check_id: row?.check_id, reason, confirm_exception: true })}>Stage exception</button>
      </div>
    </div>
  );
}
