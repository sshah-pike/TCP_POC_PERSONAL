import type { ReactNode } from "react";
import { fmtBytes, fmtMs, fmtTime, fmtUsd } from "../format";
import type { RunState } from "../types";

const NA = "Not Available";

function Row({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <>
      <span>{k}</span>
      <span className={mono ? "mono" : ""}>{v ?? "—"}</span>
    </>
  );
}

export default function Summary({ run }: { run: RunState }) {
  const r = run.request;
  const rp = run.rule_pack;
  const ai = run.cost.ai;
  const tok = (k: string) => (ai.usage && ai.usage[k] !== undefined ? ai.usage[k].toLocaleString() : NA);
  const inputLabel = { kml: "KML", coordinates: "Coordinates", offline: "Offline self-test" }[r.input_type];
  // offline scenarios carry their own operator values; the CLI only overrides what the user supplied
  const notGiven = r.input_type === "offline" ? "(scenario default)" : "(not provided)";

  return (
    <div className="card">
      <h2>EXECUTION SUMMARY</h2>
      <div className="kv">
        <Row k="Run ID" v={run.run_id} mono />
        <Row k="Decision" v={<b>{run.decision ?? "RUNNING"}</b>} />
        <Row k="Exit code" v={run.exit_code ?? "—"} mono />
        <Row k="Started" v={fmtTime(run.started_at ?? run.created_at)} />
        <Row k="Completed" v={fmtTime(run.ended_at)} />
        <Row k="Total runtime" v={fmtMs(run.runtime_ms)} />
        <Row k="HTTPS trust store" v={run.tls ? run.tls.trust_store : "not recorded"} />
      </div>

      <h3>Input</h3>
      <div className="kv">
        <Row k="Input type" v={inputLabel} />
        {r.input_type === "kml" && (
          <>
            <Row k="Input file" v={`${r.kml_filename} (${fmtBytes(r.kml_size_bytes)})`} />
            <Row k="Saved at" v={r.kml_saved_path} mono />
          </>
        )}
        {r.input_type === "offline" && <Row k="Scenario" v={`${r.offline_scenario} (input: ${r.offline_input})`} />}
        <Row k="Road type" v={r.operator.road_type ?? notGiven} />
        <Row k="Speed" v={r.operator.speed ?? notGiven} />
        <Row k="Requires lane closure" v={r.operator.requires_lane_closure ? "yes" : "no"} />
        <Row k="TA-1 options" v={r.operator.options.length ? r.operator.options.join(", ") : "none"} mono />
        <Row
          k="Advanced"
          v={`map=${r.advanced.map_provider ?? "default"}  ai=${r.advanced.ai_provider ?? "default"}  dwt=${
            r.advanced.no_dwt ? "skipped" : r.advanced.dwt_mode ?? "default"
          }`}
          mono
        />
      </div>

      <h3>Rule pack</h3>
      {rp ? (
        <div className="kv">
          <Row k="Rule pack" v={`${rp.id} v${rp.version}`} mono />
          <Row k="Status" v={rp.status} />
          <Row k="Rule pack hash" v={rp.hash} mono />
          <Row k="File" v={rp.file} mono />
          <Row k="Rule pack TA" v={rp.selected_ta} />
          <Row
            k="Selected for this run"
            v={run.selected_ta ?? `not selected (decision ${run.decision ?? "pending"})`}
          />
        </div>
      ) : (
        <div className="muted small">Rule pack was not loaded in this run{run.error ? " – see error above" : ""}.</div>
      )}

      <h3>Pipeline timing</h3>
      <table className="tbl">
        <tbody>
          {run.stages.map((s) => (
            <tr key={s.key}>
              <td>
                {s.index}. {s.title}
              </td>
              <td className="mono right">{s.duration_ms !== null ? fmtMs(s.duration_ms) : s.status === "NOT_RUN" ? "not run" : "—"}</td>
            </tr>
          ))}
          <tr className="total">
            <td>Sum of stage spans</td>
            <td className="mono right">{fmtMs(run.span_total_ms)}</td>
          </tr>
          <tr className="total">
            <td>TOTAL (runner process, incl. start-up and file writes)</td>
            <td className="mono right">{fmtMs(run.runtime_ms)}</td>
          </tr>
        </tbody>
      </table>

      <h3>Cost / usage</h3>
      <div className="kv">
        <Row k="AI model" v={ai.models.length ? ai.models.join(", ") : NA} mono />
        <Row k="AI API calls" v={ai.calls} />
        <Row k="Input tokens" v={tok("input_tokens")} mono />
        <Row k="Output tokens" v={tok("output_tokens")} mono />
        <Row k="Cache write / read tokens" v={`${tok("cache_creation_input_tokens")} / ${tok("cache_read_input_tokens")}`} mono />
        <Row k="New AI API call" v={ai.new_api_call ? "Yes" : ai.reused_from?.length ? `No – AI result reused from run ${ai.reused_from.join(", ")}` : "No"} />
        <Row k="Provider-reported cost" v={fmtUsd(ai.provider_reported_cost_usd)} />
        <Row
          k="Estimated AI cost"
          v={
            ai.estimated_cost_usd !== null
              ? `${fmtUsd(ai.estimated_cost_usd)} (estimate: recorded tokens × configured pricing${
                  run.cost.pricing_source ? `, ${run.cost.pricing_source}` : ""
                })`
              : NA
          }
        />
        {ai.note && <Row k="AI note" v={<span className="muted">{ai.note}</span>} />}
      </div>
      <table className="tbl small">
        <thead>
          <tr>
            <th>Service</th>
            <th>Provider</th>
            <th>New API call</th>
            <th>Requests</th>
            <th>Cost</th>
            <th>Note</th>
          </tr>
        </thead>
        <tbody>
          {run.cost.services.map((s) => (
            <tr key={s.service}>
              <td>{s.service}</td>
              <td className="mono">{s.provider ?? "—"}</td>
              <td>{s.new_api_call === undefined ? "—" : s.new_api_call ? "Yes" : "No"}</td>
              <td className="mono">{s.requests}</td>
              <td>{fmtUsd(s.cost_usd)}</td>
              <td className="muted">{s.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {run.lineage?.parent_cost && (
        <div className="kv">
          <Row k="Original run cost (separate)" v={`AI tokens ${JSON.stringify(run.lineage.parent_cost.ai.usage ?? "Not Available")} · Estimated ${run.lineage.parent_cost.ai.estimated_cost_usd !== null ? fmtUsd(run.lineage.parent_cost.ai.estimated_cost_usd) : "Not Available"}`} />
          <Row k="This run" v="incremental only – reused artifacts are not counted again" />
        </div>
      )}
      <div className="kv">
        <Row k="Total cost" v={<b>{fmtUsd(run.cost.total_cost_usd)}</b>} />
        <Row k="" v={<span className="muted">{run.cost.total_note}</span>} />
      </div>
    </div>
  );
}
