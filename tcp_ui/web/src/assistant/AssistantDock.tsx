import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./assistant.css";
import * as A from "./api";
import type { Attention, Json, WhoAmI } from "./types";
import { useConversation, CATEGORY_LABEL } from "./useConversation";
import ChatFlow from "./ChatFlow";
import ReviewSections from "./ReviewSections";
import ReviewCard from "./ReviewCard";
import PlacementForm from "./PlacementForm";
import ObjectForm from "./ObjectForm";
import AddFeatureForm from "./AddFeatureForm";
import { AnnotatedImage } from "./parts";
import FinalReview from "./FinalReview";
import { makeOnChoose, requestWorkspace } from "./actions";
import { AssistantMark, Icon } from "./icons";

interface RunLite { run_id: string; input?: string; decision?: string | null; state?: string }
interface Props {
  runId: string | null;                 // run currently open in RunView (default active run)
  runs: RunLite[];                      // for "Change run"
  me: WhoAmI | null;
  onOpenRun: (id: string) => void;
  mode?: "chat" | "full";               // "chat" (default for now): only the Describe-a-change chat flow is shown
}

// Chat-only mode: messages that belong to the Describe-a-change flow, and the decisions that flow can require.
const CHAT_KINDS = new Set(["USER_TEXT", "INTERPRETATION", "STRUCTURED_FORM", "DETERMINISTIC_RESULT", "CONFLICT_RESULT",
                            "FINAL_REVIEW", "CONFIRMATION", "COMMITTED", "PIPELINE_STATUS", "VERSION_RESULT", "ERROR"]);
const CHANGE_FLOW_DECISIONS = ["EXCEPTION_DECISION", "CONFIRMATION_REQUIRED", "RESUME_DECISION"];

const ACK_KEY = (run: string) => `tcp.sme.ack.${run}`;
const readAck = (run: string): string[] => { try { return JSON.parse(window.localStorage.getItem(ACK_KEY(run)) ?? "[]"); } catch { return []; } };
const writeAck = (run: string, ids: string[]) => window.localStorage.setItem(ACK_KEY(run), JSON.stringify(ids));

const MENU = [
  { id: "issues", icon: "issues", title: "Review & Resolve Issues", subs: [
    ["blocking", "Blocking issues"], ["pending", "Pending review"], ["unknown", "Unknown site facts"], ["spatial", "Spatial conflicts"],
    ["rule", "Rule conflicts"], ["ta", "TA applicability"], ["deferred", "Deferred findings"]] },
  { id: "revise", icon: "edit", title: "Revise the Draft TCP", subs: [
    ["move", "Move an existing object"], ["add", "Add an object"], ["remove", "Remove an object"], ["fact", "Change a site fact"],
    ["feature", "Add or modify a site feature"], ["workzone", "Adjust work-zone information"], ["candidate", "Use a suggested candidate position"],
    ["describe", "Describe a change (one AI interpretation, never applied automatically)"]] },
  { id: "ask", icon: "ask", title: "Ask About This Draft", subs: [] },
  { id: "image", icon: "image", title: "Review Image & Annotations", subs: [] },
] as const;

const QUESTIONS: [string, string][] = [
  ["WHY_BLOCKING", "Why is this blocking?"], ["WHAT_RERUNS", "What step will rerun?"], ["AZURE_CALLED", "Will Azure Maps be called?"],
  ["ARTIFACTS_REUSED", "What artifacts are reused?"], ["VALIDATOR_RESULT", "What is the validator result?"],
  ["VERSION_DIFF", "What changed between versions?"], ["TA_STATUS", "Is TA-1 still applicable?"],
];

export function launcherText(counts: Record<string, number> | undefined, running: boolean, hasReview: boolean): string {
  if (running) return "running";
  if (!counts) return hasReview ? "" : "";
  if (counts.BLOCKING > 0) return `${counts.BLOCKING} blocking`;
  if (counts.PENDING > 0) return `${counts.PENDING} pending`;
  return "Review complete";
}

export default function AssistantDock({ runId, runs, me, onOpenRun, mode = "chat" }: Props) {
  const chat = mode === "chat";
  const textRef = useRef<HTMLTextAreaElement>(null);
  const [activeRun, setActiveRun] = useState<string | null>(runId);
  const [summary, setSummary] = useState<Json>(null);
  const [cid, setCid] = useState<string | null>(null);
  const [cidChosen, setCidChosen] = useState(false);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [pane, setPane] = useState<string>("menu");
  const [finalOpen, setFinalOpen] = useState(false);
  const [newObjectId, setNewObjectId] = useState<string | null>(null);
  const [composeMode, setComposeMode] = useState<"change" | "ask">("change");
  const [text, setText] = useState("");
  const [localAck, setLocalAck] = useState<string[]>([]);
  const [announce, setAnnounce] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const headRef = useRef<HTMLHeadingElement>(null);
  const conv = useConversation(cid, open ? 5000 : 15000);

  // ---------------- run follows RunView (warn if leaving unconfirmed changes)
  const switchRun = useCallback((next: string | null, fromUser = false) => {
    if (next === activeRun) return true;
    const staged = conv.view?.staged?.length ?? 0;
    if (staged > 0 && !window.confirm(`The review of run ${activeRun} has ${staged} unconfirmed staged change(s). They are kept in that `
                                       + "session, but will not be applied. Switch run anyway?")) return false;
    setActiveRun(next); setCid(null); setCidChosen(false); setSummary(null); setPane("menu"); setFinalOpen(false);
    setNewObjectId(null); setNote(fromUser ? `Switched to run ${next}.` : null);
    return true;
  }, [activeRun, conv.view]);
  useEffect(() => { if (runId !== activeRun) switchRun(runId); }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------- launcher summary for the active run (never creates a conversation)
  const loadSummary = useCallback(async () => {
    if (!activeRun || !me) return;
    try { const s = await A.get<Json>(`runs/${activeRun}/assistant-summary`); setSummary(s); setLocalAck(readAck(activeRun)); }
    catch { /* run not visible / not found */ }
  }, [activeRun, me]);
  useEffect(() => { loadSummary(); }, [loadSummary]);
  useEffect(() => {
    if (!activeRun || !me) return;
    const t = window.setInterval(loadSummary, summary?.pipeline_status === "RUNNING" ? 3000 : 10000);
    return () => window.clearInterval(t);
  }, [activeRun, me, summary?.pipeline_status, loadSummary]);
  useEffect(() => {   // continue the latest conversation of THIS run unless the SME chose otherwise
    if (!cidChosen && summary?.latest_conversation_id && summary.run_id === activeRun) setCid(summary.latest_conversation_id);
  }, [summary, cidChosen, activeRun]);

  const attention: Attention | null = (cid ? conv.attention : null) ?? summary?.attention ?? null;
  const counts = attention?.counts;
  const running = summary?.pipeline_status === "RUNNING" || !!attention?.running;
  const acknowledged = cid ? conv.uiState.acknowledged_blocking : localAck;
  const blockingItems = useMemo(() => (attention?.items ?? []).filter((i) => i.category === "BLOCKING"
    && (!chat || CHANGE_FLOW_DECISIONS.includes(i.kind))), [attention, chat]);
  const unacked = blockingItems.filter((i) => !acknowledged.includes(i.id));

  // ---------------- auto-open for NEW blocking decisions only (manual close is respected)
  const lastAuto = useRef("");
  // decide only on settled data: with a conversation, its persisted UI state (acknowledgements) must be loaded first
  const settled = cid ? conv.attention !== null : !!summary && (!summary.latest_conversation_id || cidChosen);
  useEffect(() => {
    if (!settled) return;
    const key = unacked.map((i) => i.id).sort().join(",");
    if (!key || key === lastAuto.current) return;
    lastAuto.current = key;
    setOpen(true);
    setAnnounce(`SME decision required: ${unacked.map((i) => i.title).join("; ")}`);
  }, [unacked, settled]);
  useEffect(() => { if (open) headRef.current?.focus(); }, [open]);

  const close = useCallback(() => {
    const ids = blockingItems.map((i) => i.id);
    if (cid) conv.acknowledge(ids); else if (activeRun) { const m = Array.from(new Set([...localAck, ...ids])); writeAck(activeRun, m); setLocalAck(m); }
    setOpen(false); setExpanded(false);
  }, [blockingItems, cid, conv, activeRun, localAck]);

  const startReview = async () => {
    if (!activeRun) return;
    try { const v = await A.post<Json>("conversations", { run_id: activeRun }); setCid(v.conversation.conversation_id); setCidChosen(true); loadSummary(); }
    catch (e) { conv.setError((e as Error).message); }
  };
  const switchSession = (next: string | null) => {
    if ((conv.view?.staged?.length ?? 0) > 0 && !window.confirm("This session has unconfirmed staged changes (they are kept). Switch session?")) return;
    setCid(next); setCidChosen(true); setPane("menu"); setFinalOpen(false); setNewObjectId(null);
  };
  const deleteSession = async () => {
    if (!cid) return;
    const staged = conv.view?.staged?.length ?? 0;
    if (!window.confirm("Delete this review session? It is removed from the session list and closed to changes. "
                        + (staged ? `Its ${staged} unconfirmed staged change(s) are discarded. ` : "")
                        + "Confirmed versions and the audit history are kept.")) return;
    try {
      await A.post(`conversations/${cid}/archive`, { reason: "deleted by the SME from the chat window" });
      setCid(null); setCidChosen(false); setFinalOpen(false); setNewObjectId(null); setNote("Session deleted.");
      await loadSummary();
    } catch (e) { conv.setError((e as Error).message); }
  };
  const send = async () => {
    if (!text.trim()) return;
    const r = await conv.act("messages", { text }); if (r) setText("");
  };

  if (!me) return null;
  const v = conv.view;
  const canDecide = me.permissions.includes("review:decide");
  const onChoose = makeOnChoose(conv.act, setNote);
  const handlers = { act: conv.act, onChooseFinding: onChoose, canDecide, onOpenRun,
                     onCreateObject: (id: string) => { setNewObjectId(id); if (!chat) setPane("revise:add"); },
                     onOpenFinalReview: () => setFinalOpen(true),
                     onChangeDistance: (oid: string) => {
                       if (!chat) { setPane("revise:move"); return; }
                       setText(`Move ${oid} `); window.setTimeout(() => textRef.current?.focus(), 0); } };
  const status = chat ? (running ? "running" : blockingItems.length ? "decision needed" : "")
                      : launcherText(counts, running, !!cid);
  const tone = running ? "run" : (chat ? blockingItems.length : counts?.BLOCKING) ? "bad"
             : (!chat && counts?.PENDING) ? "warn" : (!chat && counts) ? "ok" : "idle";
  const findings: Json[] = v?.findings ?? [];
  const fb = (pred: (f: Json) => boolean) => findings.filter(pred).map((f) => (
    <ReviewCard key={f.finding_id} f={f} onChoose={canDecide ? onChoose(f) : undefined}
                staged={v?.staged.find((s: Json) => s.finding_id === f.finding_id)} />));

  // ---------------- pane content (menu sub-options)
  const paneBody = () => {
    const [group, sub] = pane.split(":");
    if (group === "issues") {
      const filters: Record<string, (f: Json) => boolean> = {
        blocking: (f) => f.requires_review && f.severity === "BLOCKING", pending: (f) => f.requires_review && f.severity !== "BLOCKING",
        unknown: (f) => f.state === "UNKNOWN", spatial: (f) => f.category === "FEATURE" && (f.related_objects ?? []).length > 0,
        rule: (f) => f.category === "RULE_CHECK", ta: (f) => f.category === "TA",
        deferred: (f) => (v?.staged ?? []).some((s: Json) => s.finding_id === f.finding_id && s.action === "MARK_UNRESOLVED"),
      };
      const list = fb(filters[sub] ?? filters.blocking);
      return <>{list.length ? list : <div className="muted small">No items in this category.</div>}
        {sub === "ta" && <button type="button" className="btn small" onClick={() => conv.act("ask", { question_id: "TA_STATUS" })}>Explain TA status</button>}</>;
    }
    if (group === "revise") {
      if (sub === "move") return <PlacementForm cid={cid!} objects={v.objects} onStaged={() => conv.reload()} />;
      if (sub === "add") return <ObjectForm key={newObjectId ?? "o"} cid={cid!} objects={v.objects} initialId={newObjectId ?? undefined}
                                            onStaged={() => { setNewObjectId(null); conv.reload(); }} />;
      if (sub === "remove") return <RemoveForm objects={v.objects} onSubmit={(b) => conv.act("objects/remove", b)} />;
      if (sub === "fact") return <>{fb((f) => f.category === "SITE_FACT" && f.editable)}</>;
      if (sub === "feature") return <><AddFeatureForm onSubmit={(b) => conv.act("decisions", { type: "FEATURE", action: "ADD", ...b })} />
        {fb((f) => f.category === "FEATURE")}</>;
      if (sub === "workzone") return <><div className="sme-note info"><Icon name="info" /> The work location comes from the project KML and is not
        edited here. Correct the work-related site facts below; work-zone geometry editing is a future capability.</div>
        {fb((f) => ["work.location", "work.side", "work.encroaches_traveled_way"].includes(f.subject))}</>;
      if (sub === "candidate") {
        const last = [...(v.messages ?? [])].reverse().find((m: Json) => m.kind === "CONFLICT_RESULT");
        return last ? <div className="small">Latest calculated candidates are in the conversation below (message {last.message_id.slice(-8)}).
          Use a candidate button there; nothing is applied automatically.</div> : <div className="muted small">No candidate positions yet. Evaluate a movement first.</div>;
      }
      if (sub === "describe") { return <div className="muted small">Type the change below. One bounded AI interpretation call turns it into a structured
        proposal; missing details are completed with a form (no further AI calls). Nothing is applied automatically.</div>; }
    }
    if (group === "ask") return (
      <div className="sme-qgrid">{QUESTIONS.map(([q, label]) => (
        <button key={q} type="button" className="chip" onClick={() => conv.act("ask", { question_id: q })}>{label}</button>))}
        <div className="muted small">Answers come from the active run's saved data (no AI). Other questions about this draft can be typed below;
          general MUTCD or company questions are out of scope.</div></div>);
    if (group === "image") {
      const sums = (v.messages ?? []).filter((m: Json) => m.kind === "SUMMARY");
      const img = sums.length ? sums[sums.length - 1].body.annotated_image_artifact_id : null;
      return <>{img && <AnnotatedImage artifactId={img} />}
        <div className="sme-note info"><Icon name="info" /> Correct items with the structured controls (Review &amp; Resolve or Revise) or describe a
          correction below. A new image snapshot is generated after a confirmed change. Interactive markup, drawing, measurement and
          drag-and-drop are future capabilities.</div></>;
    }
    return null;
  };

  return (
    <>
      <div className="sr-only" role="status" aria-live="assertive">{announce}</div>
      {!open && (
        <button type="button" className={`sme-launcher tone-${tone}`} onClick={() => setOpen(true)}
                aria-label={`SME Assistant${status ? `, ${status}` : ""}`}>
          <AssistantMark /> <span className="lbl">SME Assistant</span>
          {status && <span className="st">{running && <span className="spin" aria-hidden="true" />}{tone === "bad" && <Icon name="alert" />}{status}</span>}
        </button>
      )}
      {open && (
        <div className={`sme-panel ${expanded ? "expanded" : ""}`} role="dialog" aria-modal="false" aria-labelledby="sme-panel-title"
             onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } }}>
          <header className="sme-panel-head">
            <AssistantMark size={26} />
            <h2 id="sme-panel-title" tabIndex={-1} ref={headRef}>SME Assistant</h2>
            <span className="sme-who" title={me.identity.roles.join(", ")}>{me.identity.display_name}{canDecide ? "" : " · read-only"}</span>
            <span className="spacer" />
            {cid && activeRun && <button type="button" className="icon-btn" title="Open full workspace" aria-label="Open full workspace"
                                         onClick={() => { onOpenRun(activeRun); requestWorkspace(activeRun, cid); close(); }}><Icon name="layers" /></button>}
            <button type="button" className="icon-btn" aria-label={expanded ? "Compact view" : "Expand"} title={expanded ? "Compact view" : "Expand"}
                    onClick={() => setExpanded(!expanded)}><Icon name={expanded ? "collapse" : "expand"} /></button>
            <button type="button" className="icon-btn" aria-label="Close assistant" title="Close (Esc)" onClick={close}><Icon name="close" /></button>
          </header>
          {chat ? (
            <div className="sme-context slim" aria-label="Active context">
              <label>Run
                <select aria-label="Change run" value={activeRun ?? ""} onChange={(e) => switchRun(e.target.value || null, true)}>
                  {!activeRun && <option value="">— select a run —</option>}
                  {runs.slice(0, 50).map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id} · {r.decision ?? r.state ?? ""}</option>)}
                </select></label>
              {(summary?.conversations ?? []).length > 0 && (
                <label>Session
                  <select aria-label="Switch session" value={cid ?? ""} onChange={(e) => switchSession(e.target.value || null)}>
                    {summary.conversations.map((c: Json) => (
                      <option key={c.conversation_id} value={c.conversation_id}>
                        {new Date(c.created_at).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })} · {c.conversation_id.slice(-8)}
                      </option>))}
                  </select></label>)}
              {canDecide && summary?.eligible && (
                <button type="button" className="icon-btn light" aria-label="New session" title="New session" onClick={startReview}>
                  <Icon name="plus" /></button>)}
              {canDecide && cid && (
                <button type="button" className="icon-btn light danger" aria-label="Delete session" title="Delete session" onClick={deleteSession}>
                  <Icon name="trash" /></button>)}
              {running && <span className="pipe run">Pipeline running</span>}
            </div>
          ) : (
            <div className="sme-context" aria-label="Active context">
              <label>Run
                <select aria-label="Change run" value={activeRun ?? ""} onChange={(e) => switchRun(e.target.value || null, true)}>
                  {!activeRun && <option value="">— select a run —</option>}
                  {runs.slice(0, 50).map((r) => <option key={r.run_id} value={r.run_id}>{r.run_id} · {r.decision ?? r.state ?? ""}</option>)}
                </select></label>
              <span className={`pipe ${running ? "run" : ""}`}>{running ? "Pipeline running" : (summary?.decision ?? summary?.pipeline_status ?? "—")}</span>
              {(summary?.conversations ?? []).length > 0 && (
                <label>Session
                  <select aria-label="Switch session" value={cid ?? ""} onChange={(e) => {
                    if ((v?.staged?.length ?? 0) > 0 && !window.confirm("This session has unconfirmed staged changes (kept). Switch session?")) return;
                    setCid(e.target.value || null); setCidChosen(true); setPane("menu"); }}>
                    {summary.conversations.map((c: Json) => <option key={c.conversation_id} value={c.conversation_id}>{c.conversation_id.slice(-13)} · {new Date(c.created_at).toLocaleString()}</option>)}
                  </select></label>)}
              {canDecide && summary?.eligible && <button type="button" className="btn small" onClick={startReview}><Icon name="plus" /> New review session</button>}
              {v?.context && <div className="ver"><span>Evidence <b className="mono">{v.context.site_evidence_version}</b></span>
                <span>Plan <b className="mono">{v.context.plan_version ?? "none yet"}</b></span></div>}
              {counts && <div className="sme-countrow">
                {(["BLOCKING", "PENDING", "WARNING", "DONE"] as const).map((k) => counts[k] > 0 &&
                  <span key={k} className={`cnt c-${k}`}>{CATEGORY_LABEL[k]}: {counts[k]}</span>)}</div>}
            </div>
          )}
          {note && <div className="sme-note info small" role="status">{note} <button type="button" className="link" onClick={() => setNote(null)}>dismiss</button></div>}
          {conv.error && <div className="sme-note bad" role="alert"><Icon name="alert" /> {conv.error}</div>}

          <div className={`sme-panel-body ${chat ? "chatmode" : ""}`}>
            {!activeRun && <div className="sme-empty">Open a run to start an SME review.</div>}
            {activeRun && running && !cid && <div className="sme-empty"><span className="spin" aria-hidden="true" /> The pipeline is running. The assistant opens
              automatically when an SME decision is required.</div>}
            {activeRun && summary && summary.eligible === false && !running && (
              <div className="sme-empty">Not eligible for SME review: {(summary.reasons ?? []).map((r: Json) => r.message).join("; ")}</div>)}
            {activeRun && summary?.eligible && !cid && (
              <div className="sme-empty">
                <p>No review session for this run yet{!chat && counts ? ` · ${counts.BLOCKING} blocking, ${counts.PENDING} pending` : ""}.</p>
                {canDecide ? <button type="button" className="btn primary" onClick={startReview}>Start SME Review</button>
                  : <span className="muted">Read-only role: an SME reviewer must start the review.</span>}
              </div>)}

            {chat && cid && v && (() => {
              const chatMsgs = v.messages.filter((m: Json) => CHAT_KINDS.has(m.kind));
              return (
                <>
                  <ChatFlow fill messages={chatMsgs} findings={findings} staged={v.staged} h={handlers}
                            blockingAnnouncement={unacked.length ? `Decision required: ${unacked[0].title}` : ""}>
                    {chatMsgs.length === 0 && (
                      <div className="sme-empty">Describe a change to the draft TCP below, for example
                        <b> “Move S1 100 ft upstream”</b>. You will see the interpretation, any missing details as a short form,
                        the calculated result, and a final review before anything changes.</div>)}
                    {canDecide && newObjectId !== null && (
                      <ObjectForm key={newObjectId} cid={cid} objects={v.objects} initialId={newObjectId || undefined}
                                  onStaged={() => { setNewObjectId(null); conv.reload(); }} />)}
                    {finalOpen && (
                      <FinalReview cid={cid} onClose={() => setFinalOpen(false)} onEdit={() => setFinalOpen(false)}
                                   onDone={() => { setFinalOpen(false); conv.reload(); }} />)}
                  </ChatFlow>
                  {canDecide && v.staged.length > 0 && !finalOpen && (
                    <div className="sme-stagedbar" role="status">
                      <span><Icon name="layers" /> {v.staged.length} staged change{v.staged.length > 1 ? "s" : ""} (not committed)</span>
                      <button type="button" className="btn primary small" onClick={() => setFinalOpen(true)}>Review &amp; confirm</button>
                    </div>)}
                  {!canDecide && (
                    <div className="sme-readonly" role="note">
                      <Icon name="shield" /> <span>You are signed in as <b>{me.identity.display_name}</b> ({me.identity.roles.join(", ")}), which is
                        read-only. To type changes, choose an <b>SME Reviewer</b> identity in the <b>SME identity</b> menu at the top right.</span>
                    </div>)}
                  {canDecide && (
                    <form className="sme-chatcomposer" onSubmit={(e) => { e.preventDefault(); send(); }}>
                      <textarea ref={textRef} rows={1} maxLength={2000} aria-label="Describe a draft change"
                                placeholder="Describe a change, e.g. Move S1 100 ft upstream" value={text}
                                onChange={(e) => setText(e.target.value)}
                                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
                      <button type="submit" className="sme-send" aria-label="Send" title="Send (Enter)" disabled={conv.busy || !text.trim()}>
                        {conv.busy ? <span className="spin" aria-hidden="true" /> : <Icon name="send" size={18} />}</button>
                    </form>)}
                </>);
            })()}
            {!chat && cid && v && (
              <>
                {!chat && blockingItems.length > 0 && (
                  <section className="sme-blocking" aria-label="Decisions required">
                    <h3><Icon name="alert" /> Needs your decision ({blockingItems.length})</h3>
                    {blockingItems.map((i) => {
                      const f = i.finding_id ? findings.find((x) => x.finding_id === i.finding_id) : null;
                      if (f) return <ReviewCard key={i.id} f={f} onChoose={canDecide ? onChoose(f) : undefined}
                                                staged={v.staged.find((s: Json) => s.finding_id === f.finding_id)} />;
                      return (
                        <div key={i.id} className="sme-item cat-BLOCKING"><span className="cat">{i.label}</span> <b>{i.title}</b>
                          <div className="small">{i.message}</div>
                          {(i.kind === "EXCEPTION_DECISION" || i.kind === "CONFIRMATION_REQUIRED") &&
                            <button type="button" className="btn primary small" onClick={() => setFinalOpen(true)}>Open final review</button>}
                          {i.kind === "RESUME_DECISION" && canDecide && <button type="button" className="btn small" onClick={() =>
                            A.post(`plan-versions/${i.plan_version_id}/regenerate`, { conversation_id: cid }).then(conv.reload)}>Retry regeneration</button>}
                        </div>);
                    })}
                  </section>
                )}
                {!chat && blockingItems.length === 0 && pane === "menu" && (
                  <nav className="sme-menu" aria-label="How can I help with this TCP?">
                    <h3>How can I help with this TCP?</h3>
                    {MENU.map((m) => (
                      <div key={m.id} className="sme-menu-item">
                        <button type="button" className="sme-menu-main" onClick={() => setPane(m.subs.length ? `${m.id}:${m.subs[0][0]}` : m.id)}>
                          <Icon name={m.icon} /> <span>{m.title}</span> <Icon name="chevron" /></button>
                        {m.subs.length > 0 && <div className="sme-subs">{m.subs.map(([sid, label]) => (
                          <button key={sid} type="button" className="chip" onClick={() => { setPane(`${m.id}:${sid}`); if (sid === "describe") setComposeMode("change"); }}>{label}</button>))}</div>}
                      </div>))}
                  </nav>
                )}
                {!chat && pane !== "menu" && (
                  <section className="sme-pane" aria-label="Selected tool">
                    <button type="button" className="link" onClick={() => setPane("menu")}><Icon name="back" /> Back to menu</button>
                    {paneBody()}
                  </section>
                )}
                {chat && v.messages.filter((m: Json) => CHAT_KINDS.has(m.kind)).length === 0 && (
                  <div className="sme-empty">Describe a change to the draft TCP below, for example
                    <b> “Move S1 100 ft upstream”</b>. You will see the interpretation, any missing details as a short form, the
                    calculated result, and a final review before anything changes.</div>
                )}
                <ChatFlow messages={chat ? v.messages.filter((m: Json) => CHAT_KINDS.has(m.kind)) : v.messages}
                          findings={findings} staged={v.staged} h={handlers}
                          blockingAnnouncement={unacked.length ? `Decision required: ${unacked[0].title}` : ""} />
                {chat && canDecide && newObjectId !== null && (
                  <ObjectForm key={newObjectId} cid={cid} objects={v.objects} initialId={newObjectId || undefined}
                              onStaged={() => { setNewObjectId(null); conv.reload(); }} />
                )}
                {chat && canDecide && v.staged.length > 0 && !finalOpen && (
                  <div className="sme-stagedbar" role="status">
                    <span><Icon name="layers" /> {v.staged.length} staged change{v.staged.length > 1 ? "s" : ""} (not committed)</span>
                    <button type="button" className="btn primary small" onClick={() => setFinalOpen(true)}>Review &amp; confirm</button>
                  </div>
                )}
                {chat && finalOpen && (
                  <FinalReview cid={cid} onClose={() => setFinalOpen(false)} onEdit={() => setFinalOpen(false)}
                               onDone={() => { setFinalOpen(false); conv.reload(); }} />
                )}
                {canDecide && (
                  <form className="sme-composer2" onSubmit={(e) => { e.preventDefault(); send(); }}>
                    {!chat && <div className="sme-modes" role="radiogroup" aria-label="Message type">
                      <label className={composeMode === "change" ? "on" : ""}><input type="radio" name="sme-mode" checked={composeMode === "change"}
                        onChange={() => setComposeMode("change")} /> Describe a change</label>
                      <label className={composeMode === "ask" ? "on" : ""}><input type="radio" name="sme-mode" checked={composeMode === "ask"}
                        onChange={() => setComposeMode("ask")} /> Ask about this draft</label>
                    </div>}
                    <textarea ref={textRef} rows={2} maxLength={2000} aria-label={composeMode === "change" ? "Describe a draft change" : "Ask about this draft"}
                              placeholder={composeMode === "change" ? "e.g. Move S1 100 ft upstream" : "e.g. Will Azure Maps be called?"}
                              value={text} onChange={(e) => setText(e.target.value)}
                              onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }} />
                    <div className="sme-actions"><span className="muted small">{composeMode === "change"
                      ? "One bounded AI interpretation; nothing is applied automatically." : "Template answers use no AI; other draft questions use one bounded call."}</span>
                      <button type="submit" className="btn primary small" disabled={conv.busy || !text.trim()}>Send <span className="kbd">Ctrl+Enter</span></button></div>
                  </form>
                )}
                {!chat && <ReviewSections cid={cid} view={v} preview={conv.preview} attention={conv.attention} canDecide={canDecide} compact={!expanded}
                                act={conv.act} reload={conv.reload} onOpenRun={onOpenRun} onChooseFinding={onChoose}
                                finalOpen={finalOpen} setFinalOpen={setFinalOpen} newObjectId={newObjectId} setNewObjectId={setNewObjectId} />}
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function RemoveForm({ objects, onSubmit }: { objects: Json[]; onSubmit: (b: Json) => void }) {
  const [oid, setOid] = useState("");
  const [reason, setReason] = useState("");
  return (
    <form className="sme-form" onSubmit={(e) => { e.preventDefault(); onSubmit({ object_id: oid, reason }); }}>
      <div className="sme-form-title"><Icon name="form" /> Remove an object</div>
      <label>Object <select value={oid} onChange={(e) => setOid(e.target.value)} aria-label="Object to remove">
        <option value="">— select —</option>{objects.filter((o) => o.object_id !== "W1").map((o) => <option key={o.object_id}>{o.object_id}</option>)}</select></label>
      <input className="sme-input wide" aria-label="Engineering reason" placeholder="Engineering reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="sme-actions"><button type="submit" className="btn primary small" disabled={!oid || !reason.trim()}>Stage removal</button></div>
    </form>
  );
}
