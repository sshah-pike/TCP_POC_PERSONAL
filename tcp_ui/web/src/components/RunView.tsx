import { useEffect, useState } from "react";
import { evidenceUrl, getRun, stopRun } from "../api";
import { decisionClass, fmtClock } from "../format";
import type { Meta, RunState } from "../types";
import ComparisonSetup from "./ComparisonSetup";
import ResumePanel from "./ResumePanel";
import ArtifactLink from "./ArtifactLink";
import FinalDraft from "./FinalDraft";
import StageList from "./StageList";
import Summary from "./Summary";

interface Props {
  runId: string;
  meta: Meta;
  onFinished: () => void;
  onOpenRun: (runId: string) => void;
  onOpenComparison: (comparisonId: string) => void;
}

function DecisionPanel({ run }: { run: RunState }) {
  const codes = run.reason_codes.length > 0 && (
    <div className="codes">
      {run.reason_codes.map((c) => (
        <span key={c} className="code">
          {c}
        </span>
      ))}
    </div>
  );
  switch (run.decision) {
    case "SUPPORTED_AUTO":
      return (
        <div className="banner ok">
          <div className="big">SUPPORTED_AUTO – draft exported</div>
          <div>{run.message}</div>
        </div>
      );
    case "REVIEW_REQUIRED":
      return (
        <div className="banner warn">
          <div className="big">REVIEW REQUIRED</div>
          <div className="small">Reason codes:</div>
          {codes}
          <div>Pipeline stopped safely. No TCP draft was generated.</div>
          {run.message && <div className="muted small">{run.message}</div>}
        </div>
      );
    case "UNSUPPORTED_POC":
      return (
        <div className="banner bad">
          <div className="big">UNSUPPORTED POC</div>
          <div className="small">Reason codes:</div>
          {codes}
          <div>This location/scenario is outside the current POC scope. No TCP draft was generated.</div>
          {run.message && <div className="muted small">{run.message}</div>}
        </div>
      );
    case "STOPPED":
      return (
        <div className="banner warn">
          <div className="big">RUN STOPPED</div>
          <div>Stopped by the user before the pipeline finished. No TCP draft was generated; files written so far are kept.</div>
        </div>
      );
    case "FAILED":
      return (
        <div className="banner bad">
          <div className="big">PIPELINE FAILED</div>
          {run.error && (
            <pre className="viewer short">
              {run.error.error_code}: {run.error.message}
            </pre>
          )}
          <div>No TCP draft was generated.</div>
        </div>
      );
    default:
      return null;
  }
}

type Panel = { kind: "resume"; stage: string; title: string } | { kind: "compare" };

export default function RunView({ runId, meta, onFinished, onOpenRun, onOpenComparison }: Props) {
  const [run, setRun] = useState<RunState | null>(null);
  const [panel, setPanel] = useState<Panel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const [stopping, setStopping] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    let sawRunning = false;
    setRun(null);
    setError(null);
    const poll = async () => {
      try {
        const r = await getRun(runId);
        if (cancelled) return;
        setRun(r);
        setError(null);
        if (r.state === "RUNNING") {
          sawRunning = true;
          timer = window.setTimeout(poll, 1000);
        } else if (sawRunning) {
          onFinished();
        }
      } catch (e) {
        if (cancelled) return;
        setError((e as Error).message);
        timer = window.setTimeout(poll, 2000);
      }
    };
    poll();
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [runId, onFinished]);

  const running = run?.state === "RUNNING";
  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(t);
  }, [running]);

  if (!run) return <div className="card">{error ? `Cannot load run: ${error}` : "Loading…"}</div>;

  const start = Date.parse(run.started_at ?? run.created_at);
  const elapsed = running ? now - start : run.runtime_ms ?? 0;
  const sizes = Object.fromEntries(run.outputs.map((o) => [o.name, o.size_bytes]));
  const analysis = (span: string) => run.evidence.some((e) => e.producer_span === span && (e.kind === "map" || e.kind === "osm"));
  const legacy = run.evidence_compat?.status === "LEGACY";
  const stop = async () => {
    if (!window.confirm("Stop this run? The pipeline process is ended now. Files written so far are kept; a model " +
                        "request that is already in progress may still be billed by the provider.")) return;
    setStopping(true);
    try { await stopRun(run.run_id); } catch (e) { setError((e as Error).message); setStopping(false); }
  };
  const canCompare = !legacy && analysis("tcp.map.retrieve") && analysis("tcp.osm.resolve") && meta.foundry_profiles.some((p) => p.available);

  return (
    <>
      <div className="card">
        <div className="runhead">
          <h2>
            TCP Run <span className="mono">{run.run_id}</span>
          </h2>
          <span className={`pill ${running ? "run" : decisionClass(run.decision)}`}>
            {running ? "RUNNING" : run.decision ?? run.state}
          </span>
          <span className="spacer" />
          {running && (
            <button className="btn danger" onClick={stop} disabled={stopping}>{stopping ? "Stopping…" : "Stop run"}</button>
          )}
          <span>
            Overall elapsed: <b className="mono">{fmtClock(elapsed)}</b>
          </span>
        </div>
        {error && <div className="muted small">Connection problem: {error} (retrying)</div>}
        {run.lineage && (
          <div className="banner info small">
            Resumed from run{" "}
            <button className="link mono" onClick={() => onOpenRun(run.lineage!.parent_run_id)}>{run.lineage.parent_run_id}</button>
            {" "}· requested restart: <b>{run.lineage.requested_stage}</b>
            {run.lineage.actual_stage && <> · actual restart: <b>{run.lineage.actual_stage}</b></>}
            {run.lineage.ai_profile && <> · AI profile <b>{run.lineage.ai_profile}</b></>}
            {run.lineage.comparison_id && (
              <> · part of comparison{" "}
                <button className="link mono" onClick={() => onOpenComparison(run.lineage!.comparison_id!)}>{run.lineage.comparison_id}</button></>
            )}
          </div>
        )}
        {legacy && (
          <div className="banner bad small">
            <b>LEGACY / INCOMPATIBLE EVIDENCE</b> – {run.evidence_compat?.reason}. Not eligible for resume or model comparison;
            a re-run from Input, Rule Pack or Imagery acquires new evidence.
          </div>
        )}
        <DecisionPanel run={run} />
        {!running && canCompare && !panel && (
          <div className="buttons">
            <button className="btn" onClick={() => setPanel({ kind: "compare" })}>Compare Models…</button>
          </div>
        )}
        <StageList runId={run.run_id} stages={run.stages} now={now} sizes={sizes}
                   onResume={running ? undefined : (stage, title) => setPanel({ kind: "resume", stage, title })}
                   resumableStages={legacy ? ["input", "rule_pack", "imagery"] : undefined} />
      </div>

      {panel?.kind === "resume" && (
        <ResumePanel runId={run.run_id} stage={panel.stage} stageTitle={panel.title} meta={meta}
                     onStarted={onOpenRun} onCancel={() => setPanel(null)} />
      )}
      {panel?.kind === "compare" && (
        <ComparisonSetup runId={run.run_id} meta={meta} onStarted={onOpenComparison} onCancel={() => setPanel(null)} />
      )}

      {run.draft_generated && <FinalDraft run={run} />}

      {!running && <Summary run={run} />}

      {run.evidence.length > 0 && (
        <div className="card">
          <h2>Evidence artifacts</h2>
          <div className="muted small">Saved at acquisition (kept for review, resume and comparison) or reused from an earlier run by verified hash.</div>
          <table className="tbl small">
            <thead><tr><th>Artifact</th><th>Kind</th><th>Stage</th><th>Origin</th><th>SHA-256</th><th></th></tr></thead>
            <tbody>
              {run.evidence.map((e) => (
                <tr key={e.artifact_id}>
                  <td className="mono">{e.artifact_id}</td><td>{e.kind}</td><td className="mono">{e.producer_span}</td>
                  <td>{e.mode === "saved" ? "saved by this run" : <>REUSED from <button className="link mono" onClick={() => onOpenRun(e.source_run!)}>{e.source_run}</button> (API call made: No)</>}</td>
                  <td className="mono">{e.sha256.slice(0, 16)}…</td>
                  <td>{e.mode === "saved" && e.file && <a className="link" href={evidenceUrl(run.run_id, e.file)} target="_blank" rel="noreferrer">open</a>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="card">
        <h2>Files written by the pipeline</h2>
        {run.outputs.length === 0 ? (
          <div className="muted small">No output files.</div>
        ) : (
          run.outputs.map((o) => <ArtifactLink key={o.name} runId={run.run_id} name={o.name} size={o.size_bytes} />)
        )}
      </div>

      <details className="card">
        <summary>Console output</summary>
        <pre className="viewer">{run.log.join("\n") || "(no output yet)"}</pre>
      </details>
    </>
  );
}
