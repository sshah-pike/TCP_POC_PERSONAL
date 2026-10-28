import type { Json } from "./types";
import { Details, KV, fmt } from "./parts";

const ftm = (m: number | null | undefined) => (m == null ? "—" : `${m} m (${(m / 0.3048).toFixed(1)} ft)`);

// Complete deterministic impact of the staged decisions (level 1 summary, level 2 details).
export default function ImpactPreview({ p, onException }: { p: Json; onException?: (kind: "RULE_CONFLICT" | "TA_NOT_APPLICABLE", row?: Json) => void }) {
  if (!p) return null;
  const changed = p.facts.filter((r: Json) => r.kind !== "UNCHANGED" || r.changed_vs_current);
  return (
    <div className="sme-impact">
      <h4>Impact of the staged decisions (preview — nothing is committed)</h4>
      <KV rows={[
        ["Plan result", <b>{p.plan_outcome.status}</b>],
        ["Eligibility", `${p.eligibility.current.decision} → ${p.eligibility.proposed.decision}`],
        ["TA result", p.ta.proposed.message],
        ["Rule result", `${p.rules.filter((r: Json) => r.proposed === "FAIL").length} validator conflict(s) after the change`],
        ["Expected AI / external calls", `AI ${p.ai_calls_expected}; Azure Maps ${p.external_calls_expected.azure_maps}; OSM ${p.external_calls_expected.osm}; Foundry ${p.external_calls_expected.foundry_vision + p.external_calls_expected.foundry_text}`],
      ]} />
      <Details title={`Site facts: machine → current → proposed (${changed.length} changed)`} open>
        <table className="tbl small">
          <thead><tr><th>Fact</th><th>Change</th><th>Machine</th><th>Current</th><th>Proposed</th></tr></thead>
          <tbody>
            {changed.map((r: Json) => (
              <tr key={r.field} className={r.kind === "DIRECT" ? "sme-direct" : "sme-dependent"}>
                <td>{r.label}</td><td>{r.kind}</td>
                <td>{r.machine ? `${fmt(r.machine.value)} (${r.machine.status}${r.machine.confidence != null ? `, ${r.machine.confidence}` : ""})` : "—"}</td>
                <td>{fmt(r.current.value)} ({r.current.status}{r.current.source ? `, ${r.current.source}` : ""})</td>
                <td><b>{fmt(r.proposed.value)}</b> ({r.proposed.status}{r.proposed.source ? `, ${r.proposed.source}` : ""})</td>
              </tr>
            ))}
          </tbody>
        </table>
        {p.superseded_conflicts.length > 0 && <div className="small">Conflicts resolved by SME decision: {p.superseded_conflicts.map((c: Json) => c.field).join(", ")}</div>}
        {p.rejected_features.length > 0 && <div className="small">Features REJECTED_BY_SME (kept for audit, excluded from validation): {p.rejected_features.join(", ")}</div>}
      </Details>
      <Details title="TA applicability (approved structured TA data only)">
        <KV rows={[["Current TA", `${p.ta.current.ta_id} ${p.ta.current.title ?? ""} — ${p.ta.current.applicable ? "applicable" : "not applicable"}`],
                   ["Proposed", p.ta.proposed.message], ["Changed conditions", p.ta.changed_conditions.map((c: Json) => c.fact).join(", ") || "none"],
                   ["Candidate TAs found", p.ta.approved_candidates_found.join(", ") || "none"],
                   ["Restart point", p.ta.required_restart_stage ?? "—"]]} />
        {onException && p.ta.proposed.state === "CURRENT_TA_NOT_APPLICABLE" &&
          <button className="btn small" onClick={() => onException("TA_NOT_APPLICABLE")}>Proceed as plan-specific engineering exception…</button>}
      </Details>
      <Details title="Validator results (unchanged validators)">
        <table className="tbl small">
          <thead><tr><th>Check</th><th>Current</th><th>Proposed</th><th>SME disposition</th><th></th></tr></thead>
          <tbody>{p.rules.map((r: Json) => {
            const d = p.dispositions?.dispositions?.find((x: Json) => x.check_id === r.check_id);
            return (
              <tr key={r.check_id}><td className="mono">{r.check_id}</td><td>{r.rule_status_current}</td><td><b>{r.rule_status_proposed}</b></td>
                <td>{d ? d.disposition : "—"}</td>
                <td>{onException && r.proposed === "FAIL" && d?.disposition !== "ACCEPTED_WITH_SME_OVERRIDE" &&
                  <button className="btn small" onClick={() => onException("RULE_CONFLICT", r)}>SME exception…</button>}</td></tr>);
          })}</tbody>
        </table>
      </Details>
      <Details title="Placement effects">
        <table className="tbl small">
          <thead><tr><th>Object</th><th>Change</th><th>Current station</th><th>Proposed station</th><th>Δ</th></tr></thead>
          <tbody>{p.placement.map((r: Json) => (
            <tr key={r.object_id}><td className="mono">{r.object_id}</td><td>{r.change}</td><td>{ftm(r.current?.station_m)}</td>
              <td>{ftm(r.proposed?.station_m)}</td><td>{r.station_change_m == null ? "—" : ftm(r.station_change_m)}</td></tr>
          ))}</tbody>
        </table>
      </Details>
    </div>
  );
}
