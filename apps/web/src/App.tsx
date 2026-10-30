import { useCallback, useEffect, useState } from "react";
import { getMeta, listComparisons, listProjects, listRuns } from "./api";
import type { ComparisonSummary, Meta, ProjectSummary, RunSummary } from "./types";
import NewProjectForm from "./components/NewProjectForm";
import ProjectView from "./components/ProjectView";
import RunHistory, { type Selection } from "./components/RunHistory";
import RunView from "./components/RunView";
import ComparisonView from "./components/ComparisonView";
import LabelsView from "./components/LabelsView";
import IdentitySelect from "./assistant/IdentitySelect";
import AssistantDock from "./assistant/AssistantDock";
import * as Assist from "./assistant/api";
import type { AssistantStatus, WhoAmI } from "./assistant/types";

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [comparisons, setComparisons] = useState<ComparisonSummary[]>([]);
  const [assistant, setAssistant] = useState<AssistantStatus | null>(null);
  const [me, setMe] = useState<WhoAmI | null>(null);
  const [selected, setSelectedState] = useState<Selection | null>(() => {
    const m = /^#(run|comparison|labels|project)\/?([\w-]*)$/.exec(window.location.hash);  // deep link: #run/<id>
    return m ? { kind: m[1] as Selection["kind"], id: m[2] || m[1] } : null;
  });
  const setSelected = useCallback((s: Selection) => {
    setSelectedState(s);
    window.history.replaceState(null, "", `#${s.kind}/${s.kind === "labels" ? "" : s.id}`);
  }, []);

  useEffect(() => {
    getMeta().then(setMeta).catch((e: Error) => setMetaError(e.message));
    Assist.status().then(setAssistant).catch(() => setAssistant({ enabled: false, state: "DISABLED" }));
  }, []);

  const refresh = useCallback(() => {
    listProjects().then(setProjects).catch(() => undefined);
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
  const openProject = useCallback((id: string) => {
    setSelected({ kind: "project", id });
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
        <span className="spacer" />
        {assistant?.enabled ? <IdentitySelect onChange={setMe} /> : assistant && <span className="muted small">SME Review: DISABLED</span>}
      </header>
      {metaError && <div className="banner bad">Cannot reach the local TCP server: {metaError}</div>}
      <div className="layout">
        <aside className="sidebar">
          {meta && <NewProjectForm meta={meta} onCreated={openProject} />}
          <div className="card"><button className="btn" onClick={() => setSelected({ kind: "labels", id: "labels" })}>Evaluation labels…</button></div>
          <RunHistory projects={projects} runs={runs} comparisons={comparisons} selected={selected} onSelect={setSelected} />
        </aside>
        <main className="main">
          {selected?.kind === "project" && meta ? (
            <ProjectView key={selected.id} projectId={selected.id} meta={meta} onOpenRun={openRun} onChanged={refresh} />
          ) : selected?.kind === "run" && meta ? (
            <RunView key={selected.id} runId={selected.id} meta={meta} onFinished={refresh}
                     onOpenRun={openRun} onOpenComparison={openComparison}
                     assistantEnabled={!!assistant?.enabled} me={me} />
          ) : selected?.kind === "labels" ? (
            <LabelsView />
          ) : selected?.kind === "comparison" ? (
            <ComparisonView key={selected.id} comparisonId={selected.id} onOpenRun={openRun} />
          ) : (
            <div className="card empty">Create a project from a KML, or select a project or run from the history.</div>
          )}
        </main>
      </div>
      {assistant?.enabled && (
        <AssistantDock runId={selected?.kind === "run" ? selected.id : null} runs={runs} me={me} onOpenRun={openRun} />
      )}
    </div>
  );
}
