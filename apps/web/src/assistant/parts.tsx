import { useEffect, useState, type ReactNode } from "react";
import * as A from "./api";
import type { Json } from "./types";

export const STATE_TAG: Record<string, string> = {
  DETERMINED: "OK", NEEDS_CONFIRMATION: "LOW", CONFLICT: "CONFLICT", UNKNOWN: "UNKNOWN", SME_CONFIRMED: "SME", SME_EXCEPTION: "EXCEPTION",
};

// colour + text: never colour alone
export function StateBadge({ state }: { state: string }) {
  return <span className={`sme-state sme-${state}`}>{STATE_TAG[state] ?? state}</span>;
}

export function Sev({ s }: { s: string }) {
  return <span className={`sme-sev sme-sev-${s}`}>{s}</span>;
}

export function Details({ title, children, open }: { title: string; children: ReactNode; open?: boolean }) {
  return <details className="sme-details" open={open}><summary>{title}</summary>{children}</details>;
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <table className="tbl small sme-kv"><tbody>
      {rows.filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => <tr key={k}><th>{k}</th><td>{v}</td></tr>)}
    </tbody></table>
  );
}

export const fmt = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));

// Annotated image: fetched with the session header (no token in URLs), shown as a static picture.
export function AnnotatedImage({ artifactId }: { artifactId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [meta, setMeta] = useState<Json>(null);
  const [err, setErr] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const [actual, setActual] = useState(false);
  useEffect(() => {
    let u: string | null = null; let cancelled = false;
    A.get<Json>(`artifacts/${artifactId}`).then((r) => !cancelled && setMeta(r.artifact)).catch(() => undefined);
    fetch(`/api/assistant/artifacts/${encodeURIComponent(artifactId)}/file`, { headers: { "X-TCP-Session": A.getToken() ?? "" } })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.blob(); })
      .then((b) => { if (cancelled) return; u = URL.createObjectURL(b); setUrl(u); })
      .catch((e: Error) => setErr(e.message));
    return () => { cancelled = true; if (u) URL.revokeObjectURL(u); };
  }, [artifactId]);
  return (
    <div className="sme-image">
      {err && <div className="muted small">Image unavailable: {err}</div>}
      {url && (
        <>
          <div className="sme-image-tools small">
            <button className="btn small" onClick={() => setFull(true)}>Full screen</button>{" "}
            <button className="btn small" onClick={() => window.open(url, "_blank", "noopener")}>Open in new tab</button>
            <span className="muted"> · click the image to enlarge</span>
          </div>
          <img src={url} className="sme-image-thumb" onClick={() => setFull(true)}
               alt="Annotated site-understanding review image (static)" title="Click to view full screen" />
        </>
      )}
      {url && full && (
        <div className="sme-lightbox" role="dialog" aria-label="Annotated image, full screen"
             onKeyDown={(e) => e.key === "Escape" && setFull(false)} tabIndex={-1} ref={(el) => el?.focus()}>
          <div className="sme-lightbox-bar">
            <button className="btn small" onClick={() => setActual(!actual)}>{actual ? "Fit to screen" : "Actual size (100%)"}</button>{" "}
            <button className="btn small" onClick={() => window.open(url, "_blank", "noopener")}>Open in new tab</button>{" "}
            <button className="btn small" onClick={() => setFull(false)}>Close (Esc)</button>
          </div>
          <div className="sme-lightbox-body" onClick={(e) => e.target === e.currentTarget && setFull(false)}>
            <img src={url} className={actual ? "actual" : "fit"} onClick={() => setActual(!actual)}
                 alt="Annotated site-understanding review image (static, full screen)" />
          </div>
        </div>
      )}
      {meta && (
        <Details title="Image details (review artifact, not the source of truth)">
          <KV rows={[["Artifact", <span className="mono">{meta.artifact_id}</span>], ["Renderer", meta.renderer_version],
                     ["Source image", <span className="mono">{meta.source_image.artifact_id} · {meta.source_image.sha256.slice(0, 16)}…</span>],
                     ["PNG SHA-256", <span className="mono">{meta.png_sha256.slice(0, 24)}…</span>],
                     ["Not assessed", meta.not_assessed.join(", ")]]} />
        </Details>
      )}
    </div>
  );
}
