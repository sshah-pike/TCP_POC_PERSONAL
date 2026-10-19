import { useCallback, useEffect, useState } from "react";
import { getMeta, listComparisons, listRuns } from "./api";
import type { ComparisonSummary, Meta, RunSummary } from "./types";
import NewRunForm from "./components/NewRunForm";
import RunHistory, { type Selection } from "./components/RunHistory";
import RunView from "./components/RunView";
import ComparisonView from "./components/ComparisonView";
import LabelsView from "./components/LabelsView";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [comparisons, setComparisons] = useState<ComparisonSummary[]>([]);
  const [selected, setSelectedState] = useState<Selection | null>(() => {
    const m = /^#(run|comparison|labels)\/?([\w-]*)$/.exec(window.location.hash);  // deep link: #run/<id>
    return m ? { kind: m[1] as Selection["kind"], id: m[2] || m[1] } : null;
  });
  const setSelected = useCallback((s: Selection) => {
    setSelectedState(s);
    window.history.replaceState(null, "", `#${s.kind}/${s.kind === "labels" ? "" : s.id}`);
  }, []);

  useEffect(() => {
    getMeta().then(setMeta).catch((e: Error) => setMetaError(e.message));
  }, []);

  const refresh = useCallback(() => {
    listRuns().then(setRuns).catch(() => undefined);
    listComparisons().then(setComparisons).catch(() => undefined);
  }, []);

  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 4000);
    return () => window.clearInterval(t);
  }, [refresh]);

  const openRun = useCallback((id: string) => {
    setSelected({ kind: "run", id });
    refresh();
  }, [refresh, setSelected]);
  const openComparison = useCallback((id: string) => {
    setSelected({ kind: "comparison", id });
    refresh();
  }, [refresh, setSelected]);

  return (
    <div className="app">
      <header className="topbar">
        <h1>TCP POC Runner</h1>
        <span className="muted">{meta ? meta.app_version : ""}</span>
      </header>
      {metaError && <div className="banner bad">Cannot reach the local TCP server: {metaError}</div>}
      <div className="layout">
        <aside className="sidebar">
          {meta && <NewRunForm meta={meta} onStarted={openRun} />}
          <div className="card"><button className="btn" onClick={() => setSelected({ kind: "labels", id: "labels" })}>Evaluation labels…</button></div>
          <RunHistory runs={runs} comparisons={comparisons} selected={selected} onSelect={setSelected} />
        </aside>
        <main className="main">
          {selected?.kind === "run" && meta ? (
            <RunView key={selected.id} runId={selected.id} meta={meta} onFinished={refresh}
                     onOpenRun={openRun} onOpenComparison={openComparison} />
          ) : selected?.kind === "labels" ? (
            <LabelsView />
          ) : selected?.kind === "comparison" ? (
            <ComparisonView key={selected.id} comparisonId={selected.id} onOpenRun={openRun} />
          ) : (
            <div className="card empty">Start a new run, or select a previous run from the history.</div>
          )}
        </main>
      </div>
    </div>
  );
}
