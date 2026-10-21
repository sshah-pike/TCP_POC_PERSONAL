import { useCallback, useEffect, useRef, useState } from "react";
import * as A from "./api";
import type { Attention, Json } from "./types";

// One review conversation: view, impact preview and attention, plus the deterministic actions. Used by both the floating
// assistant and the full workspace, so both surfaces share the same backend state and APIs (no second implementation).
export function useConversation(cid: string | null, pollMs = 0) {
  const [view, setView] = useState<Json>(null);
  const [preview, setPreview] = useState<Json>(null);
  const [attention, setAttention] = useState<Attention | null>(null);
  const [uiState, setUiState] = useState<{ acknowledged_blocking: string[] }>({ acknowledged_blocking: [] });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const live = useRef(cid);
  live.current = cid;

  const reload = useCallback(async () => {
    if (!cid) return;
    try {
      const [v, a] = await Promise.all([A.get<Json>(`conversations/${cid}`), A.get<Json>(`conversations/${cid}/attention`)]);
      if (live.current !== cid) return;
      A.setContext(cid, v.context);
      setView(v); setAttention(a.attention); setUiState(a.ui_state ?? { acknowledged_blocking: [] }); setError(null);
      if (v.staged.length > 0) A.get<Json>(`conversations/${cid}/preview`).then((r) => live.current === cid && setPreview(r.preview)).catch(() => undefined);
      else setPreview(null);
    } catch (e) { if (live.current === cid) setError((e as Error).message); }
  }, [cid]);

  useEffect(() => { setView(null); setPreview(null); setAttention(null); if (cid) reload(); }, [cid, reload]);
  useEffect(() => {
    if (!cid || !pollMs) return;
    const t = window.setInterval(reload, pollMs);
    return () => window.clearInterval(t);
  }, [cid, pollMs, reload]);

  // every action: deterministic backend call, then reload. Stale context -> reload and surface the message.
  const act = useCallback(async <R = Json>(path: string, body: Json = {}): Promise<R | null> => {
    if (!cid) return null;
    setBusy(true); setError(null);
    try {
      const r = await A.post<R>(`conversations/${cid}/${path}`, body);
      const pv = (r as Json)?.preview; if (pv) setPreview(pv);
      await reload();
      return r;
    } catch (e) {
      const ae = e as A.ApiError;
      setError(ae.message);
      if (ae.body?.error_code === "STALE_CONTEXT" || ae.body?.error_code === "CROSS_RUN_REJECTED") await reload();
      return null;
    } finally { setBusy(false); }
  }, [cid, reload]);

  const acknowledge = useCallback(async (ids: string[]) => {
    if (!cid) return;
    const merged = Array.from(new Set([...(uiState.acknowledged_blocking ?? []), ...ids]));
    setUiState({ acknowledged_blocking: merged });
    try { const r = await A.post<Json>(`conversations/${cid}/ui-state`, { acknowledged_blocking: merged }); if (r?.ui_state) setUiState(r.ui_state); }
    catch { /* best effort: suppression is a UI preference, not a decision */ }
  }, [cid, uiState]);

  return { view, preview, attention, uiState, error, busy, reload, act, acknowledge, setError };
}

export const CATEGORY_LABEL: Record<string, string> = {
  BLOCKING: "Blocking issue", PENDING: "Pending review", WARNING: "Warning", INFO: "Information", DONE: "Completed",
};
