import type { ComparisonReport, ComparisonSummary, Evaluation, Label, LocationRow, Meta, NewProjectPayload, NewRunPayload, Project,
              ProjectInputsPayload, ProjectSummary, ResumePreview, RunState, RunSummary, Variant } from "./types";

/** An error answer of the server: its message, error_code and the whole body (for example the rejected locations). */
export class ApiError extends Error {
  status: number; code: string | null; body: { locations?: LocationRow[]; file_reasons?: string[]; missing?: Record<string, string[]> };
  constructor(status: number, body: Record<string, unknown>, fallback: string) {
    super(String(body.error ?? fallback));
    this.status = status; this.code = (body.error_code as string | undefined) ?? null; this.body = body;
  }
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status}: ${(await r.json().catch(() => ({}))).error ?? r.statusText}`);
  return r.json() as Promise<T>;
}

export const getMeta = () => getJson<Meta>("/api/meta");
export const listRuns = () => getJson<RunSummary[]>("/api/runs");
export const getRun = (id: string) => getJson<RunState>(`/api/runs/${encodeURIComponent(id)}`);

/** Closed since S3: POST /api/runs answers 400, only a project starts runs. Kept only so the orphaned NewRunForm still
 *  compiles; the S15 orphan sweep moves both to backup/orphans/. */
export async function startRun(payload: NewRunPayload): Promise<string> {
  const r = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error ?? r.statusText);
  return body.run_id as string;
}

async function projectCall<T>(method: "GET" | "POST", url: string, body?: unknown): Promise<T> {
  const r = await fetch(url, { method, cache: "no-store", headers: { "Content-Type": "application/json" },
                               body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(r.status, data, r.statusText);
  return data as T;
}

const proj = (id: string) => `/api/projects/${encodeURIComponent(id)}`;
export const listProjects = () => projectCall<ProjectSummary[]>("GET", "/api/projects");
export const getProject = (id: string) => projectCall<Project>("GET", proj(id));
/** 201 new project, 200 the same geometry reopened (project.created tells which). 422 NO_USABLE_LOCATION lists why. */
export const createProject = (payload: NewProjectPayload) => projectCall<Project>("POST", "/api/projects", payload);
export const setProjectInputs = (id: string, payload: ProjectInputsPayload) => projectCall<Project>("POST", `${proj(id)}/inputs`, payload);
export const runProject = (id: string) => projectCall<Project>("POST", `${proj(id)}/run`, {});
export const approveZoneCap = (id: string, approvedBy: string) => projectCall<Project>("POST", `${proj(id)}/approve-cap`, { approved_by: approvedBy });

export async function stopRun(runId: string): Promise<void> {
  await postJson<unknown>(`/api/runs/${encodeURIComponent(runId)}/stop`, {});
}

export function fileUrl(runId: string, name: string, download = false): string {
  return `/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}${download ? "?download=1" : ""}`;
}

export async function getText(url: string): Promise<string> {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.text();
}

async function postJson<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error ?? r.statusText);
  return data as T;
}

export function getResumePreview(runId: string, stage: string, aiProfile: string | null, evidenceMode = "single"): Promise<ResumePreview> {
  const q = new URLSearchParams({ stage, evidence_mode: evidenceMode });
  if (aiProfile) q.set("ai_profile", aiProfile);
  return getJson<ResumePreview>(`/api/runs/${encodeURIComponent(runId)}/resume-preview?${q}`);
}

export const startResume = (runId: string, stage: string, aiProfile: string | null, evidenceMode = "single") =>
  postJson<{ run_id: string }>(`/api/runs/${encodeURIComponent(runId)}/resume`, { stage, ai_profile: aiProfile, evidence_mode: evidenceMode }).then((r) => r.run_id);

export const startComparison = (sourceRunId: string, profiles: string[], variants: Variant[]) =>
  postJson<{ comparison_id: string }>("/api/comparisons", { source_run_id: sourceRunId, profiles, variants }).then((r) => r.comparison_id);
export const getEvaluation = (cid: string) => getJson<Evaluation>(`/api/comparisons/${encodeURIComponent(cid)}/evaluation`);
export const listLabels = () => getJson<Label[]>("/api/labels");
export const confirmLabel = (siteId: string, reviewer: string, reason: string, edits: Record<string, unknown>) =>
  postJson<Label>(`/api/labels/${encodeURIComponent(siteId)}/confirm`, { reviewer, reason, edits });
export const revokeLabel = (siteId: string, reviewer: string, reason: string) =>
  postJson<Label>(`/api/labels/${encodeURIComponent(siteId)}/revoke`, { reviewer, reason });

export const listComparisons = () => getJson<ComparisonSummary[]>("/api/comparisons");
export const getComparison = (id: string) => getJson<ComparisonReport>(`/api/comparisons/${encodeURIComponent(id)}`);

export function evidenceUrl(runId: string, name: string): string {
  return `/api/runs/${encodeURIComponent(runId)}/evidence/${encodeURIComponent(name)}`;
}
