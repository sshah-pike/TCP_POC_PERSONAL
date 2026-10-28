import "./assistant.css";
import { useState } from "react";
import type { Json, WhoAmI } from "./types";
import { useConversation, CATEGORY_LABEL } from "./useConversation";
import ChatFlow from "./ChatFlow";
import ReviewSections from "./ReviewSections";
import { makeOnChoose } from "./actions";
import { AssistantMark, Icon } from "./icons";

interface Props { cid: string; me: WhoAmI; onOpenRun: (id: string) => void; onClose: () => void }

// Expanded SME review workspace: the same conversation state and APIs as the floating assistant, laid out wide.
export default function SmeReviewView({ cid, me, onOpenRun, onClose }: Props) {
  const conv = useConversation(cid, 8000);
  const [finalOpen, setFinalOpen] = useState(false);
  const [newObjectId, setNewObjectId] = useState<string | null>(null);
  const [text, setText] = useState("");
  const v = conv.view;
  if (!v) return <div className="muted small">{conv.error ?? "Loading review…"}</div>;
  const canDecide = me.permissions.includes("review:decide");
  const onChoose = makeOnChoose(conv.act);
  const counts = conv.attention?.counts;
  const send = async () => { if (text.trim() && await conv.act("messages", { text })) setText(""); };
  return (
    <div className="sme-workspace">
      <header className="sme-ws-head">
        <AssistantMark size={30} />
        <div>
          <h3>SME review workspace</h3>
          <div className="sme-ws-ctx">
            <span>Run <button type="button" className="link mono" onClick={() => onOpenRun(v.head_run_id)}>{v.head_run_id}</button></span>
            <span>{v.run_state.decision}</span>
            <span>Session <b className="mono">{cid.slice(-13)}</b></span>
            <span>Evidence <b className="mono">{v.context?.site_evidence_version}</b></span>
            <span>Plan <b className="mono">{v.context?.plan_version ?? "none yet"}</b></span>
            <span>Rule pack {v.rule_pack.id} v{v.rule_pack.version}</span>
          </div>
        </div>
        <span className="spacer" />
        {counts && (["BLOCKING", "PENDING", "DONE"] as const).map((k) => counts[k] > 0 &&
          <span key={k} className={`cnt c-${k}`}>{CATEGORY_LABEL[k]}: {counts[k]}</span>)}
        <button type="button" className="btn small" onClick={conv.reload}>Refresh</button>
        <button type="button" className="btn small" onClick={onClose}>Close</button>
      </header>
      {conv.error && <div className="sme-note bad" role="alert"><Icon name="alert" /> {conv.error}</div>}
      <div className="sme-ws-grid">
        <div className="sme-ws-chat">
          <ChatFlow messages={v.messages} findings={v.findings} staged={v.staged}
                    h={{ act: conv.act, onChooseFinding: onChoose, canDecide, onOpenRun, onCreateObject: setNewObjectId,
                         onOpenFinalReview: () => setFinalOpen(true) }} />
          {canDecide && (
            <form className="sme-composer2" onSubmit={(e) => { e.preventDefault(); send(); }}>
              <textarea rows={2} maxLength={2000} aria-label="Describe a draft change or ask about this draft"
                        placeholder="Describe a change (e.g. Move S1 100 ft upstream) or ask about this draft"
                        value={text} onChange={(e) => setText(e.target.value)}
                        onKeyDown={(e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } }} />
              <div className="sme-actions"><span className="muted small">One bounded AI interpretation for change requests; template questions use none.</span>
                <button type="submit" className="btn primary small" disabled={conv.busy || !text.trim()}>Send</button></div>
            </form>
          )}
        </div>
        <div className="sme-ws-sections">
          <ReviewSections cid={cid} view={v as Json} preview={conv.preview} attention={conv.attention} canDecide={canDecide}
                          act={conv.act} reload={conv.reload} onOpenRun={onOpenRun} onChooseFinding={onChoose}
                          finalOpen={finalOpen} setFinalOpen={setFinalOpen} newObjectId={newObjectId} setNewObjectId={setNewObjectId} />
        </div>
      </div>
    </div>
  );
}
