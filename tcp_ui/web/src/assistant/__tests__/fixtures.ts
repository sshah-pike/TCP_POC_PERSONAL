import { vi } from "vitest";
import type { Json } from "../types";

// Route table for the mocked assistant API: "GET path" / "POST path" -> handler(body).
export const api = { routes: {} as Record<string, (body?: Json) => Json>, calls: [] as [string, string, Json][] };

export function mockApiModule() {
  return {
    getToken: () => "tok", setToken: () => undefined, setContext: () => undefined, getContext: () => undefined,
    ApiError: class extends Error { status = 0; body: Json = {}; },
    get: vi.fn(async (path: string) => {
      api.calls.push(["GET", path, null]);
      const key = Object.keys(api.routes).find((k) => k === `GET ${path}` || (k.endsWith("*") && `GET ${path}`.startsWith(k.slice(0, -1))));
      if (!key) throw new Error(`unmocked GET ${path}`);
      return api.routes[key]();
    }),
    post: vi.fn(async (path: string, body: Json) => {
      api.calls.push(["POST", path, body]);
      const h = api.routes[`POST ${path}`];
      return h ? h(body) : {};
    }),
    status: vi.fn(), identities: vi.fn(), whoami: vi.fn(), selectIdentity: vi.fn(), endSession: vi.fn(),
  };
}

export const ME = { identity: { subject_id: "sme.1", display_name: "SME", roles: ["SME_REVIEWER"] },
                    permissions: ["review:read", "review:decide", "message:submit", "changeset:confirm", "exception:confirm"] } as Json;
const zero = { BLOCKING: 0, PENDING: 0, WARNING: 0, INFO: 0, DONE: 0 };

export function attention(blocking: string[] = [], pending = 0): Json {
  const items = [
    ...blocking.map((id) => ({ id, kind: "FINDING", category: "BLOCKING", label: "Blocking issue", title: `Finding ${id}`, finding_id: id, section: "SITE" })),
    ...Array.from({ length: pending }, (_, i) => ({ id: `P${i}`, kind: "FINDING", category: "PENDING", label: "Pending review", title: `Pending ${i}`, section: "SITE" })),
  ];
  return { items, counts: { ...zero, BLOCKING: blocking.length, PENDING: pending }, blocking_ids: blocking, running: false };
}

export function summary(run: string, att: Json, conv: string | null = null): Json {
  return { run_id: run, pipeline_status: "FINISHED", decision: "REVIEW_REQUIRED", eligible: true, attention: att,
           conversations: conv ? [{ conversation_id: conv, run_id: run, created_at: "2026-10-21T10:00:00Z" }] : [],
           latest_conversation_id: conv };
}

export function finding(id: string, extra: Json = {}): Json {
  return { finding_id: id, category: "SITE_FACT", subject: "road.road_type", label: `Fact ${id}`, entity_id: "road.road_type", value: null,
           state: "UNKNOWN", severity: "BLOCKING", requires_review: true, evidence_sources: ["OPERATOR"], choices: [
             { action: "CORRECT", value: "RURAL", label: "RURAL" }], style: {}, ...extra };
}

export function view(cid: string, run: string, opts: { staged?: Json[]; findings?: Json[]; messages?: Json[] } = {}): Json {
  return {
    conversation: { conversation_id: cid, run_id: run }, head_run_id: run, run_state: { decision: "REVIEW_REQUIRED" },
    findings: opts.findings ?? [], staged: opts.staged ?? [], messages: opts.messages ?? [], objects: [
      { object_id: "W1", object_type: "WORK_LOCATION" }, { object_id: "S1", object_type: "SIGN", sign_code: "W20-1", approach: "INCREASING_STATION", station_m: 627 }],
    context: { conversation_id: cid, base_run_id: run, run_id: run, site_evidence_version: "machine:SITE-X", plan_version: "baseline", context_hash: "h" },
    lineage: { plan_versions: [] }, rule_pack: { id: "RP", version: "1" }, summary: {}, plan: null,
  };
}

export function routesFor(run: string, cid: string | null, sum: Json, conv?: Json, att?: Json) {
  api.routes = {
    [`GET runs/${run}/assistant-summary`]: () => sum,
    ...(cid ? {
      [`GET conversations/${cid}`]: () => conv,
      [`GET conversations/${cid}/attention`]: () => ({ attention: att ?? sum.attention, context: conv.context, ui_state: { acknowledged_blocking: [] } }),
      [`GET conversations/${cid}/preview`]: () => ({ preview: null }),
    } : {}),
  };
}
