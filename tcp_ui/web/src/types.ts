// Shapes returned by tcp_ui/server.py (see tcp_ui/store.py). Display-only.

export type StageStatus =
  | "WAITING" | "RUNNING" | "COMPLETED" | "WARNING" | "REVIEW" | "ERROR" | "FAILED" | "UNSUPPORTED" | "NOT_RUN";
export type Decision = "SUPPORTED_AUTO" | "REVIEW_REQUIRED" | "ERROR" | "UNSUPPORTED_POC" | "FAILED" | "STOPPED";
export type InputType = "kml" | "coordinates" | "offline";

export interface Span {
  name: string;
  started_at: string;
  ended_at: string | null;
  status: string | null;
  duration_ms: number | null;
  attributes: Record<string, unknown>;
}

/** Sanitized technical cause of a provider failure (diagnostic only; the decision uses pipeline codes). */
export interface Diagnostic {
  provider: string | null;
  pipeline_error_code: string | null;
  category: string;
  exception_type: string;
  message: string;
  http_status: number | null;
  duration_ms: number | null;
  span: string | null;
}

export interface Stage {
  index: number;
  key: string;
  title: string;
  status: StageStatus;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  spans: Span[];
  messages: string[];
  problems: string[];
  artifacts: string[];
  diagnostics: Diagnostic[];
  reuse: Reuse[];
  reuse_rejected: { kind: string; reason: string; source_run: string | null }[];
  new_calls: { service: string; provider: string; requests: number; duration_ms: number; purpose?: string }[];
  steps?: Span[];  // AI Vision: the two-call agent's steps (tcp.agent.* spans)
}

export interface Reuse { kind: string; artifact_id: string | null; source_run: string | null; sha256: string | null; api_call: boolean }

export interface EvidenceEntry {
  artifact_id: string; kind: string; mode: "saved" | "reference"; file: string | null; sha256: string;
  size_bytes: number | null; producer_span: string | null; produced_by_run: string | null;
  source_run: string | null; source_artifact_id: string | null; created_at: string;
}

export interface Lineage {
  parent_run_id: string; requested_stage: string; actual_stage: string | null; reuse_kinds: string[];
  ai_provider: string | null; ai_profile: string | null; comparison_id: string | null;
  parent_cost: Cost | null; parent_decision: Decision | null; preview: ResumePreview | null;
}

export interface PreviewReused {
  stage: string; title: string; kind: string; source_run: string; artifact: string; file: string; sha256: string;
  api_call: boolean; conditional?: boolean;
}

export interface ResumePreview {
  parent_run_id: string; requested_stage: string; predicted_actual_stage: string; moved_earlier: boolean;
  move_reason: string | null; dependency_changes: string[]; reused: PreviewReused[];
  rerun: { stage: string; title: string; external_call: string | null; reason: string }[];
  ai_provider: string | null; ai_profile: string | null; note: string;
  evidence_mode: string; legacy: boolean; legacy_reason: string | null;
}

export interface FoundryProfile {
  name: string; display_name: string; api: string; backend: string; description: string | null; deployment: string | null; effort: string | null;
  enabled: boolean; backend_implemented: boolean; available: boolean; default: boolean;
  capabilities: Record<string, unknown> | null;
}

export interface OutputFile { name: string; size_bytes: number }

export interface RulePackInfo {
  id: string; version: string; status: string; hash: string; selected_ta: string; file?: string;
}

export interface ErrorInfo { error_code: string; message: string; details?: unknown }

export interface RunRequest {
  input_type: InputType;
  kml_filename?: string;
  kml_size_bytes?: number;
  kml_saved_path?: string;
  offline_scenario?: string;
  offline_input?: string;
  operator: { road_type: string | null; speed: number | null; requires_lane_closure: boolean; options: string[] };
  advanced: { map_provider: string | null; ai_provider: string | null; dwt_mode: string | null; no_dwt: boolean;
              ai_profile?: string | null; evidence_mode?: string };
}

export interface CostService {
  service: string; provider: string | null; requests: number; cost_usd: number | null; note: string;
  new_api_call?: boolean; reused_from?: string[];
}

export interface Cost {
  ai: {
    calls: number;
    models: string[];
    usage: Record<string, number> | null;
    provider_reported_cost_usd: number | null;
    estimated_cost_usd: number | null;
    note: string | null;
    reused_from?: string[];
    new_api_call?: boolean;
  };
  services: CostService[];
  total_cost_usd: number | null;
  total_note: string;
  pricing_source: string | null;
}

export interface DwtInfo {
  status?: string; mode?: string; outputs?: string[]; error_code?: string; message?: string; details?: unknown;
}

export interface RunState {
  run_id: string;
  created_at: string;
  request: RunRequest;
  state: "RUNNING" | "FINISHED" | "INTERRUPTED";
  started_at: string | null;
  ended_at: string | null;
  runtime_ms: number | null;
  exit_code: number | null;
  decision: Decision | null;
  reason_codes: string[];
  message: string | null;
  error: ErrorInfo | null;
  stages: Stage[];
  span_total_ms: number;
  rule_pack: RulePackInfo | null;
  plan: { plan_id: string | null; plan_hash: string | null };
  selected_ta: string | null;
  dwt: DwtInfo | null;
  draft_generated: boolean;
  outputs: OutputFile[];
  log: string[];
  tls: { ssl_context: string; trust_store: string } | null;
  cost: Cost;
  evidence: EvidenceEntry[];
  lineage: Lineage | null;
  evidence_compat: { status: "OK" | "LEGACY" | "NONE"; reason: string | null } | null;
}

export interface RunSummary {
  run_id: string;
  created_at: string;
  input: string;
  state: RunState["state"];
  decision: Decision | null;
  runtime_ms: number | null;
  rule_pack: string | null;
  estimated_cost_usd: number | null;
  parent_run_id: string | null;
  requested_stage: string | null;
  comparison_id: string | null;
}

export interface ComparisonSummary {
  comparison_id: string; source_run_id: string; created_at: string; profiles: string[];
  children: { profile: string; run_id: string }[];
}

export interface ComparisonColumn {
  run_id: string; profile: string; evidence_mode: string; label: string; views: string[];
  vision_mode: string; osm_claims: boolean; centerline_views: boolean; grounding: Record<string, unknown> | null; state: string | null; backend: string | null; deployment: string | null;
  model: string | null; decision: Decision | null; reason_codes: string[]; ai_status: string | null;
  ai_error: { error_code: string; message: string } | null; schema_errors: string[] | null;
  raw_response: string | null; observation: Record<string, unknown> | null;
  ai_artifact: { artifact_id: string; sha256: string } | null; ai_duration_ms: number | null;
  usage: Record<string, number> | null; estimated_cost_usd: number | null; image_quality: string | null;
  reused: Reuse[]; new_external_calls: { service: string }[];
  fusion: { inputs_complete: boolean | null; conflicts: number; site_model_id: string | null } | null;
  eligibility: { decision: string | null; reason_codes: string[] | null } | null;
  draft_generated: boolean | null; plan_id: string | null;
  metrics: { resolved: number; unresolved: number; low_confidence: number; below_threshold: string[] };
}

export interface ComparisonRow {
  section: string; field: string; values: unknown[]; differs: boolean; unknown_vs_resolved: boolean;
  below_threshold?: boolean[];
}

export interface ComparisonReport {
  comparison_id: string; source_run_id: string; created_at: string; profiles: string[]; reused: PreviewReused[];
  modes: string[]; phase: string; skipped: { profile: string; evidence_mode: string; reason: string }[];
  prep: { state: string; ok?: boolean; error?: string; views?: string[] } | null;
  complete: boolean; confidence_threshold: number; columns: ComparisonColumn[]; rows: ComparisonRow[];
  totals: { tokens: Record<string, number> | null; estimated_cost_usd: number | null; cost_note: string | null;
            new_map_calls: number; new_osm_calls: number };
  note: string;
}

export interface Meta {
  app_version: string;
  offline_scenarios: string[];
  offline_aliases: Record<string, string>;
  map_providers: string[];
  ai_providers: string[];
  dwt_modes: string[];
  dwt_config_present: boolean;
  road_types: string[];
  supported_road_types: string[];
  rule_pack: RulePackInfo | null;
  rule_pack_error: ErrorInfo | null;
  pricing_source: string | null;
  foundry_profiles: FoundryProfile[];
  resume_stages: string[];
}

export interface NewRunPayload {
  input_type: InputType;
  kml?: { filename: string; content_base64: string };
  lat?: string;
  lon?: string;
  offline_scenario?: string;
  offline_input?: string;
  operator: { road_type: string; speed: string; requires_lane_closure: boolean; options: { key: string; value: string }[] };
  advanced: { map_provider: string; ai_provider: string; dwt_mode: string; no_dwt: boolean; ai_profile: string; evidence_mode: string };
}

export interface Variant { evidence_mode: string; vision_mode: string; osm_claims: boolean; centerline_views: boolean }

export interface EvalRow {
  field: string; predicted: unknown; status: string; confidence: number | null; label: unknown; outcome: string;
  scored: boolean; evidence: string | null; evidence_image: string | null; check: string | null;
}

export interface EvalColumn {
  run_id: string; profile: string; label: string; vision_mode: string; evidence_mode: string; decision: string | null;
  ai_status: string | null; ai_duration_ms: number | null; usage: Record<string, number> | null;
  estimated_cost_usd: number | null; model: string | null; rows: EvalRow[]; counts: Record<string, number>;
  checks: { id: string; result: string; detail: Record<string, unknown> }[] | null;
}

export interface Evaluation {
  comparison_id: string; source_run_id: string; complete: boolean; scored: boolean; note: string;
  label: { site_id: string; status: string; confirmed_by: string | null; confirmed_at: string | null;
           confirm_reason: string | null; drafted_by: string | null; drafted_at: string | null } | null;
  columns: EvalColumn[];
}

export interface LabelField { value: unknown; tolerance: number | null; note: string | null;
  evidence: { run: string; artifact: string; sha256: string; file?: string }[] }

export interface Label {
  site_id: string; name: string | null; status: "DRAFT" | "CONFIRMED"; source_run_id: string;
  work_reference: { latitude: number; longitude: number }; fields: Record<string, LabelField>;
  drafted_by: string; drafted_at: string; confirmed_by: string | null; confirmed_at: string | null;
  confirm_reason: string | null; history: { action: string; by: string; at: string; reason: string }[];
}
