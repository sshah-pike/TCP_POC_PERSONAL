import type { Decision, StageStatus } from "./types";

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms.toFixed(1)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function fmtClock(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(Math.floor(s / 3600))}:${p(Math.floor((s % 3600) / 60))}:${p(s % 60)}`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function fmtBytes(n: number | undefined): string {
  if (n === undefined) return "—";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

export function fmtUsd(v: number | null | undefined): string {
  return v === null || v === undefined ? "Not Available" : `$${v.toFixed(4)}`;
}

export const STATUS_LABEL: Record<StageStatus, string> = {
  WAITING: "Waiting", RUNNING: "Running", COMPLETED: "Completed", WARNING: "Warning", REVIEW: "Review required",
  FAILED: "Failed", UNSUPPORTED: "Unsupported", NOT_RUN: "Not run",
};

export const STATUS_ICON: Record<StageStatus, string> = {
  WAITING: "○", RUNNING: "◉", COMPLETED: "✓", WARNING: "!", REVIEW: "!", FAILED: "✕", UNSUPPORTED: "✕", NOT_RUN: "–",
};

export function decisionClass(d: Decision | null | undefined): string {
  if (d === "SUPPORTED_AUTO") return "ok";
  if (d === "REVIEW_REQUIRED" || d === "STOPPED") return "warn";
  if (d === "UNSUPPORTED_POC" || d === "FAILED") return "bad";
  return "run";
}
