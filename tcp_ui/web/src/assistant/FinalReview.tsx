import { useEffect, useState } from "react";
import * as A from "./api";
import ExceptionDialog from "./ExceptionDialog";
import type { Json } from "./types";
import { Details, KV, fmt } from "./parts";
import ImpactPreview from "./ImpactPreview";

interface Props { cid: string; onClose: () => void; onEdit: () => void; onDone: (r: Json) => void }

// Full change review before any consequential commit. Confirmation sends the exact review hash (stale -> rejected).
export default function FinalReview({ cid, onClose, onEdit, onDone }: Props) {
  const [r, setR] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState("fusion");
  const [exc, setExc] = useState<Json>(null);
  const stageException = async (payload: Json) => {
    setErr(null);
    try { await A.post(`conversations/${cid}/exceptions`, payload); setExc(null); setR(null); load(); }   // new review + new hash
    catch (e) { setErr((e as Error).message); }
  };
  const load = () => A.get<Json>(`conversations/${cid}/review`).then(setR).catch((e: Error) => setErr(e.message));
  useEffect(() => { load(); }, [cid]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!r) return <div className="card">{err ?? "Building the full change review…"}</div>;
  const rv = r.review;
  const go = async (mode: string) => {
    setBusy(true); setErr(null);
    try { onDone(await A.post<Json>(`conversations/${cid}/confirm`, { review_sha256: r.review_sha256, mode, resume_stage: stage })); }
    catch (e) {
      const ae = e as A.ApiError; setErr(ae.message);
      if (ae.body?.error_code === "STALE_REVIEW") load();
    } finally { setBusy(false); }
  };
  const p = { facts: rv.site.facts, superseded_conflicts: rv.site.superseded_conflicts, rejected_features: rv.site.rejected_features,
              plan_outcome: rv.plan_outcome, eligibility: rv.eligibility ?? { current: { decision: "(see run)" }, proposed: { decision: rv.plan_outcome.status } },
              ta: rv.ta, rules: rv.rules, placement: rv.geometry.placement, ai_calls_expected: rv.expected_calls.ai_text,
              external_calls_expected: { azure_maps: rv.expected_calls.azure_maps, osm: rv.expected_calls.osm,
                                         foundry_vision: rv.expected_calls.foundry_vision, foundry_text: 0 } };
  return (
    <div className="card sme-final">
      <h3>Full change review — confirm before anything is changed</h3>
      {rv.blocking.length > 0 && (
        <div className="banner bad small">
          Blocked: {rv.blocking.map((b: Json) => b.message).join("; ")}
          {rv.blocking.flatMap((b: Json) => b.resolutions ?? []).map((x: Json) => (
            <div key={x.check_id ?? x.kind} className="sme-resolve">
              <b>{x.check_id ?? "TA-1 not applicable"}</b>{x.objects?.length ? ` (${x.objects.join(", ")})` : ""}: rule status CONFLICT.{" "}
              {x.note && <span>{x.note} </span>}
              {x.can_request_exception
                ? <button className="btn small" onClick={() => setExc(x)}>Request SME exception…</button>
                : <span className="muted">Cannot be accepted as an exception: {x.why_not}</span>}
            </div>
          ))}
          {rv.blocking.some((b: Json) => (b.resolutions ?? []).length) &&
            <div className="muted">Alternatively, use “Edit request” to change or remove the staged move.</div>}
        </div>
      )}
      {exc && <ExceptionDialog kind={exc.check_id ? "RULE_CONFLICT" : "TA_NOT_APPLICABLE"}
                               row={{ check_id: exc.check_id, rule_id: exc.check_id, current: "PASS", proposed: "FAIL" }} ta={rv.ta}
                               onCancel={() => setExc(null)} onSubmit={stageException} />}
      <KV rows={[
        ["Requested changes", rv.request.structured_actions.map((a: Json) => `${a.key} ${a.action ?? ""} ${a.value !== undefined ? "→ " + fmt(a.value) : ""}`).join("; ") || "—"],
        ["Messages", rv.request.messages.map((m: Json) => `${m.message_id} (sha256 ${String(m.message_sha256).slice(0, 12)}…)`).join("; ") || "structured actions only (no AI)"],
        ["Draft status", `${rv.versions.proposed_status} → after regeneration: ${rv.versions.expected_status_after_regeneration}`],
        ["Active SME exceptions", rv.exceptions.length ? rv.exceptions.map((e: Json) => `${e.exception_id} (${e.type})`).join(", ") : "none"],
        ["Versions", `evidence ${rv.versions.parent_site_evidence_version} → ${rv.versions.new_site_evidence_version ?? "(unchanged)"}; plan ${rv.versions.parent_plan_version ?? "(none)"} → ${rv.versions.proposed_plan_version}`],
        ["Expected calls", `AI ${rv.expected_calls.ai_text}, Azure Maps ${rv.expected_calls.azure_maps}, OSM ${rv.expected_calls.osm}, Foundry ${rv.expected_calls.foundry_vision} (strict replay)`],
      ]} />
      <ImpactPreview p={p} />
      <Details title="Geometry, spatial conflicts, unsupported objects">
        <pre className="viewer short">{JSON.stringify({ movements: rv.geometry.movements, spatial_conflicts: rv.geometry.spatial_conflicts, objects: rv.objects }, null, 1)}</pre>
      </Details>
      <Details title="SME dispositions (validators unchanged)">
        <pre className="viewer short">{JSON.stringify(rv.dispositions, null, 1)}</pre>
      </Details>
      <Details title="Artifacts: reused / regenerated / new / invalidated for the child version">
        <KV rows={[["Reused", rv.artifacts.reused.map((x: Json) => `${x.kind} ${x.artifact} (${x.source_run})`).join(", ")],
                   ["Regenerated", rv.artifacts.regenerated.join(", ")], ["New", rv.artifacts.new.join(", ")],
                   ["Invalidated for child", rv.artifacts.invalidated_for_child.join("; ") || "—"]]} />
      </Details>
      <Details title="Pipeline resume">
        <table className="tbl small"><thead><tr><th>Stage</th><th>Allowed</th><th>Why</th></tr></thead><tbody>
          {rv.resume.allowed_choices?.map((c: Json) => (
            <tr key={c.stage}><td>{c.stage}{c.recommended ? " (recommended)" : ""}</td><td>{c.allowed ? "yes" : "no"}</td><td>{c.why_safe ?? c.why_not}</td></tr>
          ))}
        </tbody></table>
        <label className="small">Resume from <select value={stage} onChange={(e) => setStage(e.target.value)}>
          {rv.resume.allowed_choices?.filter((c: Json) => c.allowed).map((c: Json) => <option key={c.stage}>{c.stage}</option>)}
        </select></label>
      </Details>
      <Details title="Technical audit (level 3)">
        <KV rows={[["Review SHA-256", <span className="mono">{r.review_sha256}</span>], ["Rule pack", `${rv.rule_pack.id} v${rv.rule_pack.version} ${rv.rule_pack.hash.slice(0, 16)}…`],
                   ["Policy", `${rv.policy.id} v${rv.policy.version} ${rv.policy.sha256.slice(0, 16)}…`], ["Heads", JSON.stringify(rv.heads)]]} />
      </Details>
      {err && <div className="banner bad small">{err}</div>}
      <div className="buttons">
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn" onClick={onClose}>Return to review</button>
        <button className="btn" onClick={onEdit}>Edit request</button>
        <button className="btn" disabled={busy || !rv.modes.SAVE_SITE_FACTS_ONLY.available} onClick={() => go("SAVE_SITE_FACTS_ONLY")}>Save corrected site facts only</button>
        <button className="btn" disabled={busy || !rv.modes.SAVE_PROPOSED_REVISION.available} onClick={() => go("SAVE_PROPOSED_REVISION")}>Save proposed revision (no pipeline)</button>
        <button className="btn primary" disabled={busy || !rv.modes.CONFIRM_AND_REGENERATE.available} onClick={() => go("CONFIRM_AND_REGENERATE")}>Confirm changes and regenerate draft TCP</button>
      </div>
    </div>
  );
}
