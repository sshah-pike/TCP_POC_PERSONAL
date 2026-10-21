// SME Review Assistant API client. The opaque session token (never an identity) is sent in X-TCP-Session.
import type * as T from "./types";

const TOKEN_KEY = "tcp.sme.session";
export const getToken = () => window.sessionStorage.getItem(TOKEN_KEY);
export const setToken = (t: string | null) =>
  t ? window.sessionStorage.setItem(TOKEN_KEY, t) : window.sessionStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  constructor(public status: number, public body: T.ErrorBody) {
    super(body.error ?? body.message ?? `HTTP ${status}`);
  }
}

async function req<R>(method: "GET" | "POST", path: string, body?: unknown): Promise<R> {
  const headers: Record<string, string> = {};
  const t = getToken();
  if (t) headers["X-TCP-Session"] = t;
  if (method === "POST") headers["Content-Type"] = "application/json";
  const r = await fetch(`/api/assistant/${path}`, {
    method, headers, cache: "no-store", body: method === "POST" ? JSON.stringify(body ?? {}) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data);
  return data as R;
}

// Active review context per conversation (run / conversation / site-evidence / plan version / hash). Attached to every
// write on that conversation so the backend rejects stale or cross-run submissions (STALE_CONTEXT, CROSS_RUN_REJECTED).
const CONTEXTS: Record<string, T.ReviewContext> = {};
export const setContext = (cid: string, ctx: T.ReviewContext | null | undefined) => { if (ctx) CONTEXTS[cid] = ctx; };
export const getContext = (cid: string): T.ReviewContext | undefined => CONTEXTS[cid];
const NO_CONTEXT = /\/(ui-state)$/;

export const get = <R>(path: string) => req<R>("GET", path);
export function post<R>(path: string, body?: unknown): Promise<R> {
  const m = /^conversations\/([^/]+)\/.+/.exec(path);
  if (m && CONTEXTS[m[1]] && !NO_CONTEXT.test(path) && body && typeof body === "object" && !("context" in (body as object)))
    body = { ...(body as object), context: CONTEXTS[m[1]] };
  return req<R>("POST", path, body);
}
export const fileUrl = (artifactId: string) => `/api/assistant/artifacts/${encodeURIComponent(artifactId)}/file?session=1`;

export const status = () => get<T.AssistantStatus>("status");
export const identities = () => get<T.IdentityList>("identities");
export const whoami = () => get<T.WhoAmI>("session");
export async function selectIdentity(subjectId: string): Promise<T.Identity> {
  const r = await post<{ session_token: string; identity: T.Identity }>("sessions", { subject_id: subjectId });
  setToken(r.session_token);
  return r.identity;
}
export async function endSession(): Promise<void> {
  try { await post("sessions/end", {}); } finally { setToken(null); }
}
