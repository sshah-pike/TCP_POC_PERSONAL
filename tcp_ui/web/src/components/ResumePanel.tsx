import { useEffect, useState } from "react";
import { getResumePreview, startResume } from "../api";
import type { Meta, ResumePreview } from "../types";

interface Props {
  runId: string;
  stage: string;
  stageTitle: string;
  meta: Meta;
  onStarted: (runId: string) => void;
  onCancel: () => void;
}

/** Confirmation preview for "Re-run from this step": what will be reused and what will re-run. */
export default function ResumePanel({ runId, stage, stageTitle, meta, onStarted, onCancel }: Props) {
  const profiles = meta.foundry_profiles.filter((p) => p.available);
  const [profile, setProfile] = useState<string>((profiles.find((p) => p.default) ?? profiles[0])?.name ?? "");
  const [evidenceMode, setEvidenceMode] = useState("single");
  const [preview, setPreview] = useState<ResumePreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setPreview(null); setError(null);
    getResumePreview(runId, stage, profile || null, evidenceMode).then(setPreview).catch((e: Error) => setError(e.message));
  }, [runId, stage, profile, evidenceMode]);

  const aiReruns = preview?.rerun.some((r) => r.stage === "vision") ?? false;

  async function start() {
    setBusy(true); setError(null);
    try {
      onStarted(await startResume(runId, stage, aiReruns ? profile || null : null, evidenceMode));
    } catch (e) {
      setError((e as Error).message); setBusy(false);
    }
  }

  return (
    <div className="card resume">
      <h2>Re-run from “{stageTitle}”</h2>
      <div className="muted small">Creates a NEW run linked to {runId}; the original run is not changed.</div>
      {error && <div className="banner bad small">{error}</div>}
      {!preview ? (
        !error && <div className="muted small">Checking saved artifacts…</div>
      ) : (
        <>
          {preview.legacy && (
            <div className="banner bad small">{preview.legacy_reason} – reuse is not allowed; only a re-run from Input,
              Rule Pack or Imagery (fresh acquisition) can start.</div>
          )}
          {preview.moved_earlier && (
            <div className="banner warn small">
              Restart point moved earlier to <b>{preview.predicted_actual_stage}</b>: {preview.move_reason}
            </div>
          )}
          {preview.dependency_changes.length > 0 && (
            <div className="banner warn small">Changed since the source run: {preview.dependency_changes.join("; ")}</div>
          )}
          {aiReruns && (
            <div className="field">
              <label className="label">AI model profile for the re-run</label>
              <select value={profile} onChange={(e) => setProfile(e.target.value)}>
                {profiles.map((p) => (
                  <option key={p.name} value={p.name}>{p.display_name} ({p.deployment}, {p.api})</option>
                ))}
              </select>
              <label className="label">AI evidence</label>
              <select value={evidenceMode} onChange={(e) => setEvidenceMode(e.target.value)}>
                <option value="single">single-resolution (overview only)</option>
                <option value="multi">multi-resolution (overview + 3 close views)</option>
              </select>
            </div>
          )}
          <h3>Reused</h3>
          {preview.reused.length === 0 ? (
            <div className="muted small">Nothing is reused.</div>
          ) : (
            <table className="tbl small">
              <thead><tr><th>Stage</th><th>Source run</th><th>Artifact</th><th>Artifact hash</th><th>API call</th></tr></thead>
              <tbody>
                {preview.reused.map((r) => (
                  <tr key={r.stage + r.artifact}>
                    <td>{r.title}{r.conditional ? " (if the request matches)" : ""}</td>
                    <td className="mono">{r.source_run}</td>
                    <td className="mono">{r.artifact} ({r.file})</td>
                    <td className="mono">{r.sha256.slice(0, 16)}…</td>
                    <td>No</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h3>Re-run</h3>
          <table className="tbl small">
            <thead><tr><th>Stage</th><th>Reason</th><th>External API call expected</th></tr></thead>
            <tbody>
              {preview.rerun.map((r) => (
                <tr key={r.stage}>
                  <td>{r.title}</td>
                  <td>{r.reason}</td>
                  <td>{r.external_call ?? "No (local)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="muted small">{preview.note}</div>
        </>
      )}
      <div className="buttons">
        <button className="primary inline" disabled={!preview || busy || (preview.legacy && preview.reused.length > 0)} onClick={start}>
          {busy ? "Starting…" : "Start re-run"}
        </button>
        <button className="link" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
