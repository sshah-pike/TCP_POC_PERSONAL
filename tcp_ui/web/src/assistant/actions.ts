import type { Choice } from "./ReviewCard";
import type { Json } from "./types";

// Review-card button -> deterministic backend action (no AI). Shared by the floating assistant and the workspace.
export function makeOnChoose(act: (path: string, body?: Json) => Promise<Json>, onUnsupported?: (msg: string) => void) {
  return (f: Json) => (c: Choice, extra: Json) => {
    const base = { finding_id: f.finding_id, reason: extra.reason };
    if (f.category === "SITE_FACT")
      return act("decisions", { ...base, type: "FACT", field: f.subject, action: c.action, value: c.input ? extra.value : c.value });
    if (f.category === "FEATURE") {
      if (c.action === "SET_SIDEWALK") return act("decisions", { ...base, type: "SIDEWALK", side: f.side, present: c.value });
      const action = ({ CONFIRM_FEATURE: "CONFIRM", REJECT_FEATURE: "REJECT", MODIFY_FEATURE: "MODIFY" } as Record<string, string>)[c.action];
      return act("decisions", { ...base, type: "FEATURE", action, feature_key: f.subject, station_m: extra.station_m, side: extra.side });
    }
    if (c.action === "REQUEST_EXCEPTION")
      return act("exceptions", { type: "RULE_CONFLICT", check_id: f.subject, reason: extra.reason, confirm_exception: true });
    onUnsupported?.("Use the Change Set section for this decision.");
    return Promise.resolve(null);
  };
}

// Workspace hand-off: the floating assistant asks RunView's SME Review section to open a conversation.
type Pending = { runId: string; cid: string } | null;
let pending: Pending = null;
export const WORKSPACE_EVENT = "tcp-sme-workspace";
export function requestWorkspace(runId: string, cid: string) {
  pending = { runId, cid };
  window.dispatchEvent(new CustomEvent(WORKSPACE_EVENT, { detail: pending }));
}
export function takeWorkspaceRequest(runId: string): string | null {
  if (pending && pending.runId === runId) { const c = pending.cid; pending = null; return c; }
  return null;
}
