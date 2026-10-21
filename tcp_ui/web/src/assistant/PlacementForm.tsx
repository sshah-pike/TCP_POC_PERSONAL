import { useState } from "react";
import * as A from "./api";
import type { Json } from "./types";
import { Details, KV, fmt } from "./parts";

const ft = (m: number | null | undefined) => (m == null ? "—" : `${m.toFixed(2)} m (${(m / 0.3048).toFixed(1)} ft)`);

// Structured placement controls for EXISTING objects (no canvas, no AI). All geometry is calculated by the backend.
export default function PlacementForm({ cid, objects, onStaged }: { cid: string; objects: Json[]; onStaged: (r: Json) => void }) {
  const movable = objects.filter((o) => o.object_type !== "WORK_LOCATION");
  const [oid, setOid] = useState(movable[0]?.object_id ?? "");
  const [dir, setDir] = useState("UPSTREAM");
  const [dist, setDist] = useState("100");
  const [unit, setUnit] = useState("FT");
  const [keep, setKeep] = useState(true);
  const [reason, setReason] = useState("");
  const [ev, setEv] = useState<Json>(null);
  const [req, setReq] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);

  const evaluate = async (r: Json) => {
    setErr(null); setReq(r);
    try { setEv((await A.post<Json>(`conversations/${cid}/placements/evaluate`, r)).evaluation); }
    catch (e) { setErr((e as Error).message); setEv(null); }
  };
  const stage = async (r: Json) => {
    setErr(null);
    try { onStaged(await A.post<Json>(`conversations/${cid}/placements`, { ...r, reason })); setEv(null); }
    catch (e) { setErr((e as Error).message); }
  };
  const keepCurrent = async () => { onStaged(await A.post<Json>(`conversations/${cid}/placements/keep`, { object_id: oid })); setEv(null); };
  const m = ev?.movement;
  return (
    <details className="sme-details" open><summary>Move an existing device (structured; calculated along the saved road alignment)</summary>
      <div className="sme-choices">
        <select value={oid} onChange={(e) => setOid(e.target.value)}>
          {movable.map((o) => <option key={o.object_id} value={o.object_id}>{o.object_id} {o.sign_code ?? o.object_type} ({o.approach ?? "-"})</option>)}
        </select>
        <select value={dir} onChange={(e) => setDir(e.target.value)}><option>UPSTREAM</option><option>DOWNSTREAM</option></select>
        <input className="sme-input" value={dist} onChange={(e) => setDist(e.target.value)} />
        <select value={unit} onChange={(e) => setUnit(e.target.value)}><option>FT</option><option>M</option></select>
        <label className="small"><input type="checkbox" checked={keep} onChange={(e) => setKeep(e.target.checked)} /> preserve lateral offset</label>
        <button className="btn small" onClick={() => evaluate({ object_id: oid, direction: dir, distance: parseFloat(dist), unit, preserve_lateral_offset: keep })}>Evaluate</button>
      </div>
      {err && <div className="banner bad small">{err}</div>}
      {m && (
        <div className="sme-impact">
          {ev.blocking.length > 0 && <div className="banner bad small"><b>Placement conflict detected</b> — nothing has been changed.</div>}
          <KV rows={[
            ["Requested movement", `${m.requested.operation} ${m.object_id} ${m.requested.direction ?? ""} ${m.requested.distance ?? ""} ${m.requested.unit ?? ""}`],
            ["Calculated movement (along alignment)", ft(m.actual_along_alignment_m)], ["Straight-line distance", ft(m.straight_line_m)],
            ["Current coordinate / station / offset", `${m.current.latitude}, ${m.current.longitude} · ${ft(m.current.station_m)} · ${m.current.offset_m} m ${m.current.side}`],
            ["Proposed coordinate / station / offset", `${m.proposed.latitude}, ${m.proposed.longitude} · ${ft(m.proposed.station_m)} · ${m.proposed.offset_m} m ${m.proposed.side}`],
            ["Lateral offset preserved", m.lateral_offset_preserved ? "yes" : "no"], ["Method", m.method],
            ["Rule requirement", `${ev.rule_requirement.requirement} (${ev.rule_requirement.rule_distance_ft} ft): ${ev.rule_requirement.current} → ${ev.rule_requirement.proposed}`],
            ["TA impact", `${ev.ta_impact.current_ta} ${ev.ta_impact.remains_applicable ? "remains applicable" : "NOT applicable"}`],
            ["Artifact impact", `Azure Maps required: ${ev.artifact_impact.azure_maps_required ? "yes" : "no"}; ${ev.artifact_impact.reuse}`],
            ["Plan result if staged", ev.plan_outcome.status], ["Exceptions needed", ev.exceptions_needed.join(", ") || "none"],
          ]} />
          <Details title={`Spatial relationships (${ev.spatial_conflicts.length})`} open={ev.blocking.length > 0}>
            <table className="tbl small"><thead><tr><th>Severity</th><th>Relationship</th><th>Feature</th><th>Source / confidence</th><th>Distance / overlap</th></tr></thead>
              <tbody>{ev.spatial_conflicts.map((x: Json, i: number) => (
                <tr key={i}><td>{x.severity}</td><td>{x.relationship}</td><td>{x.feature ? `${x.feature.type} ${x.feature.feature_id}` : "—"}</td>
                  <td>{x.feature ? `${x.feature.source ?? "-"} ${x.feature.confidence ?? ""} ${x.feature.status ?? ""}` : x.explanation ?? ""}</td>
                  <td>{fmt(x.overlap_m ?? x.distance_m ?? x.distance_to_boundary_m)}</td></tr>))}</tbody></table>
          </Details>
          {ev.candidates && (
            <Details title="Deterministic alternatives (never applied automatically)" open>
              {ev.candidates.map((cnd: Json) => (
                <div key={cnd.kind} className="small">
                  <b>{cnd.label}</b> — station {ft(cnd.station_m)}; blocking spatial: {cnd.blocking_spatial.join(", ") || "none"}; <i>{cnd.note}</i>{" "}
                  {cnd.kind === "ORIGINAL"
                    ? <button className="btn small" onClick={keepCurrent}>Keep current position</button>
                    : <button className="btn small" onClick={() => evaluate({ object_id: oid, station_m: cnd.station_m, candidate_kind: cnd.kind })}>Evaluate this candidate</button>}
                </div>))}
            </Details>
          )}
          <input className="sme-input wide" placeholder="reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div className="buttons">
            <button className="btn" onClick={keepCurrent}>Keep current position</button>
            <button className="btn primary" disabled={!reason.trim()} onClick={() => stage(req)}>
              {ev.blocking.length || ev.exceptions_needed.length ? "Stage anyway (exceptions required before confirmation)" : "Stage this move"}</button>
          </div>
        </div>
      )}
    </details>
  );
}
