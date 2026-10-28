import { useEffect, useState } from "react";
import type { RunState } from "../types";
import * as A from "./api";
import type { Json, WhoAmI } from "./types";
import SmeReviewView from "./SmeReviewView";
import { WORKSPACE_EVENT, takeWorkspaceRequest } from "./actions";

// Entry point under a finished run when the assistant is enabled: eligibility, existing reviews, start review.
export default function SmeReviewEntry({ run, me, onOpenRun }: { run: RunState; me: WhoAmI | null; onOpenRun: (id: string) => void }) {
  const [elig, setElig] = useState<Json>(null);
  const [convs, setConvs] = useState<Json[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setElig(null); setConvs([]); setOpen(null); setErr(null);
    if (!me) return;
    A.get<Json>(`runs/${run.run_id}/eligibility`).then(setElig).catch((e: Error) => setErr(e.message));
    A.get<Json>(`conversations?run_id=${encodeURIComponent(run.run_id)}`).then((r) => setConvs(r.conversations))
      .catch(() => undefined);
  }, [run.run_id, me]);

  // floating assistant "Open full workspace" hand-off
  useEffect(() => {
    const pending = takeWorkspaceRequest(run.run_id); if (pending) setOpen(pending);
    const on = (e: Event) => {
      const d = (e as CustomEvent).detail;
      if (d?.runId === run.run_id) { takeWorkspaceRequest(run.run_id); setOpen(d.cid);
        window.setTimeout(() => document.getElementById("sme-workspace")?.scrollIntoView({ behavior: "smooth" }), 50); }
    };
    window.addEventListener(WORKSPACE_EVENT, on); return () => window.removeEventListener(WORKSPACE_EVENT, on);
  }, [run.run_id]);

  const start = async () => {
    setBusy(true); setErr(null);
    try { const v = await A.post<Json>("conversations", { run_id: run.run_id }); setOpen(v.conversation.conversation_id); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="card" id="sme-workspace">
      <h2>SME Review</h2>
      {!me && <div className="muted small">Select an SME identity (top right) to review this run.</div>}
      {err && <div className="banner bad small">{err}</div>}
      {me && elig && !elig.eligible && (
        <div className="muted small">Not eligible for SME review: {elig.reasons.map((r: Json) => r.message).join("; ")}</div>
      )}
      {me && elig?.eligible && !open && (
        <div className="buttons">
          {elig.can_start && <button className="btn primary" onClick={start} disabled={busy}>{busy ? "Starting…" : "Start SME review"}</button>}
          {convs.map((c) => (
            <button key={c.conversation_id} className="btn" onClick={() => setOpen(c.conversation_id)}>
              Open review {c.conversation_id.slice(-8)} ({new Date(c.created_at).toLocaleString()})
            </button>
          ))}
        </div>
      )}
      {open && me && <SmeReviewView cid={open} me={me} onOpenRun={onOpenRun} onClose={() => setOpen(null)} />}
    </div>
  );
}
