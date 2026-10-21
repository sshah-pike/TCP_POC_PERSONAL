export interface ErrorBody {
  error?: string; message?: string; error_code?: string; recoverable?: boolean; actions?: string[];
  details?: Record<string, unknown>;
}
export interface AssistantStatus { enabled: boolean; state: "ENABLED" | "DISABLED"; profiles?: { name: string; display_name: string; enabled: boolean }[] }
export interface Identity {
  subject_id: string; display_name: string; roles: string[]; identity_provider: string; authentication_status: string;
  tenant_id: string; entra_object_id: string; upn: string; session_id: string;
}
export interface IdentityList { identity_provider: string; identities: { subject_id: string; display_name: string; roles: string[] }[]; configured: boolean; note: string | null }
export interface WhoAmI { identity: Identity; permissions: string[] }
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type Json = any;
export interface ReviewContext {
  conversation_id: string; base_run_id: string; run_id: string; site_evidence_version: string; plan_version: string | null;
  context_hash: string;
}
export type Category = "BLOCKING" | "PENDING" | "WARNING" | "INFO" | "DONE";
export interface AttentionItem {
  id: string; kind: string; category: Category; label: string; title: string; message?: string | null;
  finding_id?: string; section?: "SITE" | "CHANGE"; checks?: string[]; plan_version_id?: string;
}
export interface Attention { items: AttentionItem[]; counts: Record<Category, number>; blocking_ids: string[]; running: boolean }
