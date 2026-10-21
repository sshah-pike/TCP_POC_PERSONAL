import { useEffect, useRef, useState, type ReactNode } from "react";
import * as A from "./api";
import type { Attention, Json } from "./types";
import { AnnotatedImage, Details, StateBadge, fmt } from "./parts";
import ReviewCard, { type Choice } from "./ReviewCard";
import ImpactPreview from "./ImpactPreview";
import ExceptionDialog from "./ExceptionDialog";
import FinalReview from "./FinalReview";
import PlacementForm from "./PlacementForm";
import ObjectForm from "./ObjectForm";
import AddFeatureForm from "./AddFeatureForm";
import { Icon } from "./icons";

// Accordion: collapsed by default; opens automatically when `attention` turns true (new required decision); the SME can
// always open/close it manually. A manual choice is kept until a NEW attention key appears.
export function Section({ id, title, icon, badge, badgeTone, attention, attentionKey, children }: {
  id: string; title: string; icon: string; badge?: number; badgeTone?: "bad" | "warn" | "info"; attention: boolean;
  attentionKey: string; children: ReactNode;
}) {
  const [manual, setManual] = useState<boolean | null>(null);
  const lastKey = useRef(attentionKey);
  useEffect(() => { if (attentionKey !== lastKey.current) { lastKey.current = attentionKey; if (attention) setManual(null); } },
    [attentionKey, attention]);
  const open = manual ?? attention;
  return (
    <section className={`sme-acc ${open ? "open" : ""}`} aria-labelledby={`${id}-h`}>
      <h3 id={`${id}-h`} className="sme-acc-h">
        <button type="button" aria-expanded={open} aria-controls={`${id}-b`} onClick={() => setManual(!open)}>
          <span className="chev"><Icon name="chevron" /></span><Icon name={icon} /> <span className="t">{title}</span>
          {badge !== undefined && badge > 0 && <span className={`sme-count ${badgeTone ?? "info"}`} aria-label={`${badge} items`}>{badge}</span>}
          {attention && <span className="sme-attn">needs attention</span>}
        </button>
      </h3>
      <div id={`${id}-b`} className="sme-acc-b" hidden={!open}>{open && children}</div>
    </section>
  );
}

export interface SectionsProps {
  cid: string; view: Json; preview: Json; attention: Attention | null; canDecide: boolean; compact?: boolean;
  act: (path: string, body?: Json) => Promise<Json>; reload: () => void; onOpenRun?: (id: string) => void;
  onChooseFinding: (f: Json) => (c: Choice, extra: Json) => void;
  finalOpen: boolean; setFinalOpen: (o: boolean) => void; newObjectId?: string | null; setNewObjectId?: (id: string | null) => void;
  focus?: string | null;
}

export default function ReviewSections(p: SectionsProps) {
  const { view: v, attention: att, preview } = p;
  const [factsPreview, setFactsPreview] = useState<Json>(null);
  const [exc, setExc] = useState<{ kind: "RULE_CONFLICT" | "TA_NOT_APPLICABLE"; row?: Json } | null>(null);
  const [done, setDone] = useState<Json>(null);
  useEffect(() => { A.get<Json>(`conversations/${p.cid}/preview`).then((r) => setFactsPreview(r.preview)).catch(() => undefined); },
    [p.cid, v?.staged?.length, v?.context?.context_hash]);
  if (!v) return null;
  const items = att?.items ?? [];
  const blockingSite = items.filter((i) => i.category === "BLOCKING" && i.section === "SITE");
  const blockingChange = items.filter((i) => i.category === "BLOCKING" && i.section === "CHANGE");
  const pending = items.filter((i) => i.category === "PENDING" || i.category === "WARNING");
  const byId: Record<string, Json> = Object.fromEntries(v.findings.map((f: Json) => [f.finding_id, f]));
  const summaries = v.messages.filter((m: Json) => m.kind === "SUMMARY");
  const image = summaries.length ? summaries[summaries.length - 1].body.annotated_image_artifact_id : null;
  const rejected = v.findings.filter((f: Json) => f.status === "REJECTED_BY_SME");
  const unknown = v.findings.filter((f: Json) => f.state === "UNKNOWN");
  const fp = preview ?? factsPreview;
  const staged = v.staged ?? [];
  const card = (f: Json) => <ReviewCard key={f.finding_id} f={f} onChoose={p.canDecide ? p.onChooseFinding(f) : undefined}
                                        staged={staged.find((s: Json) => s.finding_id === f.finding_id)} />;
  return (
    <div className="sme-sections">
      <Section id={`${p.cid}-site`} title="Site Evidence & Understanding" icon="image" badge={blockingSite.length} badgeTone="bad"
               attention={blockingSite.length > 0 || p.focus === "site"} attentionKey={blockingSite.map((i) => i.id).join(",") + (p.focus ?? "")}>
        <div className="sme-meta-row"><span>Site evidence <b className="mono">{v.context?.site_evidence_version}</b></span>
          <span>Run <b className="mono">{v.head_run_id}</b></span></div>
        {blockingSite.length > 0 && <div className="sme-sub"><h4>Blocking site questions</h4>{blockingSite.map((i) => byId[i.finding_id!] && card(byId[i.finding_id!]))}</div>}
        {image && <AnnotatedImage artifactId={image} />}
        <h4>Site facts - machine, SME and effective</h4>
        <div className="sme-tablewrap"><table className="tbl small sme-facts">
          <thead><tr><th>Fact</th><th>Machine</th><th>SME decision</th><th>Effective</th><th>Confidence / source</th></tr></thead>
          <tbody>{(fp?.facts ?? []).map((r: Json) => {
            const f = v.findings.find((x: Json) => x.subject === r.field);
            const sme = r.current?.source && String(r.current.source).startsWith("SME") ? `${r.current.source.replace("SME_", "").toLowerCase()}: ${fmt(r.current.value)}` : "—";
            return (
              <tr key={r.field}><td>{r.label}</td><td>{fmt(r.machine?.value)} <span className="muted">{r.machine?.status}</span></td>
                <td>{sme}</td><td><b>{fmt(r.current?.value)}</b> {f && <StateBadge state={f.state} />}</td>
                <td className="muted">{f?.confidence != null ? f.confidence.toFixed(2) : "—"} · {(f?.evidence_sources ?? []).join(", ")}</td></tr>);
          })}</tbody></table></div>
        {unknown.length > 0 && <p className="small"><b>Unknown:</b> {unknown.map((f: Json) => f.label).join(", ")}</p>}
        {rejected.length > 0 && <p className="small"><b>Rejected by SME (kept for audit, excluded from validation):</b> {rejected.map((f: Json) => f.entity_id).join(", ")}</p>}
        {p.canDecide && <AddFeatureForm onSubmit={(b) => p.act("decisions", { type: "FEATURE", action: "ADD", ...b })} />}
      </Section>

      <Section id={`${p.cid}-pending`} title="Pending Engineering Review" icon="issues" badge={pending.length} badgeTone="warn"
               attention={p.focus === "pending"} attentionKey={p.focus ?? ""}>
        {pending.length === 0 ? <div className="muted small">Nothing pending. Non-blocking items appear here without opening the assistant.</div> :
          pending.map((i) => (byId[i.finding_id ?? ""] && i.category === "PENDING") ? card(byId[i.finding_id!]) : (
            <div key={i.id} className={`sme-item cat-${i.category}`}><span className="cat">{i.label}</span> <b>{i.title}</b>
              {i.message && <span className="muted"> - {i.message}</span>}</div>))}
      </Section>

      <Section id={`${p.cid}-change`} title="Change Set & Decisions" icon="layers" badge={staged.length + blockingChange.length}
               badgeTone={blockingChange.length ? "bad" : "info"}
               attention={staged.length > 0 || blockingChange.length > 0 || p.finalOpen || p.focus === "change"}
               attentionKey={`${staged.map((s: Json) => s.key).join(",")}|${blockingChange.map((i) => i.id).join(",")}|${p.finalOpen}|${p.focus}`}>
        {blockingChange.map((i) => (
          <div key={i.id} className="sme-item cat-BLOCKING" role="alert"><span className="cat">{i.label}</span> <b>{i.title}</b>
            <span className="muted"> - {i.message}</span>
            {i.kind === "RESUME_DECISION" && p.canDecide && <button type="button" className="btn small" onClick={() =>
              A.post(`plan-versions/${i.plan_version_id}/regenerate`, { conversation_id: p.cid }).then(p.reload)}>Retry regeneration</button>}
            {(i.kind === "CONFIRMATION_REQUIRED" || i.kind === "EXCEPTION_DECISION") && <button type="button" className="btn small" onClick={() => p.setFinalOpen(true)}>Open final review</button>}
          </div>))}
        <h4>Staged operations ({staged.length})</h4>
        {staged.length === 0 ? <div className="muted small">No staged changes. Use the guided controls or describe a change.</div> : (
          <ul className="sme-staged">{staged.map((s: Json) => (
            <li key={s.key}><span className="mono">{s.key}</span> {s.action?.replace(/_/g, " ").toLowerCase()} {s.value !== undefined ? `→ ${fmt(s.value)}` : ""}
              {s.reason ? <span className="muted"> ({s.reason})</span> : null}
              {p.canDecide && <button type="button" className="link" onClick={() => p.act("decisions/remove", { key: s.key })}>remove</button>}</li>))}</ul>)}
        {preview && staged.length > 0 && <ImpactPreview p={preview} onException={p.canDecide ? (kind, row) => setExc({ kind, row }) : undefined} />}
        {exc && <ExceptionDialog kind={exc.kind} row={exc.row} ta={preview?.ta} onCancel={() => setExc(null)}
                                 onSubmit={async (b) => { await p.act("exceptions", b); setExc(null); }} />}
        {p.canDecide && v.objects.length > 0 && !p.compact && (
          <>
            <PlacementForm cid={p.cid} objects={v.objects} onStaged={() => p.reload()} />
            <ObjectForm key={p.newObjectId ?? "obj"} cid={p.cid} objects={v.objects} initialId={p.newObjectId ?? undefined}
                        onStaged={() => { p.setNewObjectId?.(null); p.reload(); }} />
          </>
        )}
        {p.canDecide && staged.length > 0 && !p.finalOpen && (
          <div className="sme-actions"><button type="button" className="btn primary" onClick={() => p.setFinalOpen(true)}>Review all changes before confirming…</button></div>)}
        {p.finalOpen && <FinalReview cid={p.cid} onClose={() => p.setFinalOpen(false)} onEdit={() => p.setFinalOpen(false)}
                                     onDone={(r) => { setDone(r); p.setFinalOpen(false); p.reload(); }} />}
        {done && <div className="sme-note ok"><Icon name="check" /> Confirmed {done.change_set_id}
          {done.plan_version_id && <> · {done.plan_version_id}</>}{done.resume_attempt && <> · regeneration run {done.resume_attempt.run_id}</>}</div>}
        <Details title="Version lineage">
          <table className="tbl small"><thead><tr><th>Plan version</th><th>Status</th><th>Run</th></tr></thead>
            <tbody>{(v.lineage.plan_versions ?? []).map((x: Json) => (
              <tr key={x.plan_version_id}><td className="mono">{x.plan_version_id}</td><td>{x.status}</td>
                <td>{x.run_id ? <button type="button" className="link mono" onClick={() => p.onOpenRun?.(x.run_id)}>{x.run_id}</button> : "—"}</td></tr>))}
            </tbody></table>
        </Details>
        <Details title="Technical audit (level 3)"><pre className="viewer short">{JSON.stringify({ context: v.context, lineage: v.lineage, plan: v.plan }, null, 1)}</pre></Details>
      </Section>
    </div>
  );
}
