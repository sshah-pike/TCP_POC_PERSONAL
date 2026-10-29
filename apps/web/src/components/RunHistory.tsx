import { useEffect, useState } from "react";
import { decisionClass, fmtMs, fmtTime, fmtUsd, projectStatusClass } from "../format";
import type { ComparisonSummary, ProjectSummary, RunSummary } from "../types";
import ServiceErrorBadge from "./ServiceErrorBadge";

export type Selection = { kind: "run" | "comparison" | "labels" | "project"; id: string };

interface Props {
  projects?: ProjectSummary[];
  runs: RunSummary[];
  comparisons: ComparisonSummary[];
  selected: Selection | null;
  onSelect: (s: Selection) => void;
}

const STORE_KEY = "tcp-history-open";  // group ids the user expanded (kept in this browser only)

function loadOpen(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(STORE_KEY) || "[]") as string[]); } catch { return new Set(); }
}

/** Run history as a tree: project -> its zone runs -> resumed runs -> comparisons -> per-model child runs. Runs that
 *  belong to no project (made before S3) are listed under "Other runs". Every node with sub-items is a group that can be
 *  collapsed / expanded. */
export default function RunHistory({ projects = [], runs, comparisons, selected, onSelect }: Props) {
  const [open, setOpen] = useState<Set<string>>(loadOpen);
  useEffect(() => { localStorage.setItem(STORE_KEY, JSON.stringify([...open])); }, [open]);

  const byId = new Map(runs.map((r) => [r.run_id, r]));
  const resumes = (parent: string) => runs.filter((r) => r.parent_run_id === parent && !r.comparison_id);
  const compsOf = (source: string) => comparisons.filter((c) => c.source_run_id === source);
  const roots = runs.filter((r) => !r.parent_run_id || !byId.has(r.parent_run_id));
  const known = new Set(projects.map((p) => p.project_id));
  const inProject = (r: RunSummary) => !!r.project_id && known.has(r.project_id);
  const projectRoots = (pid: string) => roots.filter((r) => r.project_id === pid);
  const otherRoots = roots.filter((r) => !inProject(r));

  // ids of every group node and the groups that contain a given id (so the selected item is never hidden)
  const groups: string[] = [];
  const ancestors = new Map<string, string[]>();
  const walk = (id: string, path: string[]) => {
    ancestors.set(id, path);
    const kids = [...resumes(id).map((r) => r.run_id), ...compsOf(id).map((c) => c.comparison_id)];
    if (kids.length) groups.push(id);
    resumes(id).forEach((r) => walk(r.run_id, [...path, id]));
    compsOf(id).forEach((c) => {
      ancestors.set(c.comparison_id, [...path, id]);
      if (c.children.length) groups.push(c.comparison_id);
      c.children.forEach((ch) => ancestors.set(ch.run_id, [...path, id, c.comparison_id]));
    });
  };
  roots.forEach((r) => walk(r.run_id, inProject(r) ? [r.project_id as string] : []));
  projects.forEach((p) => { if (projectRoots(p.project_id).length) groups.push(p.project_id); });
  const forced = new Set(selected ? ancestors.get(selected.id) ?? [] : []);
  const isOpen = (id: string) => open.has(id) || forced.has(id);
  const toggle = (id: string) => setOpen((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });

  const twisty = (id: string, count: number) => (
    <button type="button" className="twisty" title={isOpen(id) ? "Collapse" : "Expand"}
            onClick={(e) => { e.stopPropagation(); toggle(id); }}>
      {isOpen(id) ? "▾" : "▸"} <span className="muted small">{count}</span>
    </button>
  );

  const runItem = (r: RunSummary, depth: number, label?: string) => {
    const subs = resumes(r.run_id); const comps = compsOf(r.run_id); const count = subs.length + comps.length;
    return (
      <div key={r.run_id}>
        <div className="hist-row" style={{ marginLeft: depth * 14 }}>
          {count > 0 ? twisty(r.run_id, count) : <span className="twisty-pad" />}
          <button
            className={`hist ${selected?.kind === "run" && selected.id === r.run_id ? "sel" : ""}`}
            onClick={() => onSelect({ kind: "run", id: r.run_id })}
          >
            <div className="hist-top">
              <span className="mono small">{depth > 0 ? "↳ " : ""}{r.run_id}</span>
              <span>
                <span className={`pill ${r.state === "RUNNING" ? "run" : decisionClass(r.decision)}`}>
                  {r.state === "RUNNING" ? "RUNNING" : r.decision ?? r.state}
                </span>{" "}
                <ServiceErrorBadge codes={r.service_error} />
              </span>
            </div>
            <div className="small">
              {label ?? r.input}
              {r.parent_run_id && !label && <span className="muted"> · resumed from {r.requested_stage}</span>}
            </div>
            <div className="muted small">
              {fmtTime(r.created_at)} · {fmtMs(r.runtime_ms)} · AI cost {fmtUsd(r.estimated_cost_usd)}
            </div>
          </button>
        </div>
        {count > 0 && isOpen(r.run_id) && (
          <>
            {subs.map((c) => runItem(c, depth + 1))}
            {comps.map((c) => (
              <div key={c.comparison_id}>
                <div className="hist-row" style={{ marginLeft: (depth + 1) * 14 }}>
                  {c.children.length > 0 ? twisty(c.comparison_id, c.children.length) : <span className="twisty-pad" />}
                  <button
                    className={`hist comp ${selected?.kind === "comparison" && selected.id === c.comparison_id ? "sel" : ""}`}
                    onClick={() => onSelect({ kind: "comparison", id: c.comparison_id })}
                  >
                    <div className="hist-top">
                      <span className="mono small">↳ {c.comparison_id}</span>
                      <span className="pill run">COMPARISON</span>
                    </div>
                    <div className="small">{c.children.length} models: {c.profiles.join(", ")}</div>
                  </button>
                </div>
                {isOpen(c.comparison_id) && c.children.map((ch) => {
                  const cr = byId.get(ch.run_id);
                  return cr ? runItem(cr, depth + 2, `model: ${ch.profile}`) : null;
                })}
              </div>
            ))}
          </>
        )}
      </div>
    );
  };

  const projectItem = (p: ProjectSummary) => {
    const kids = projectRoots(p.project_id);
    return (
      <div key={p.project_id} data-testid="history-project">
        <div className="hist-row">
          {kids.length > 0 ? twisty(p.project_id, kids.length) : <span className="twisty-pad" />}
          <button className={`hist proj ${selected?.kind === "project" && selected.id === p.project_id ? "sel" : ""}`}
                  onClick={() => onSelect({ kind: "project", id: p.project_id })}>
            <div className="hist-top">
              <span className="small"><b>{p.name}</b></span>
              <span className={`pill ${projectStatusClass(p.status)}`}>{p.status}</span>
            </div>
            <div className="muted small">{p.zones} zone{p.zones === 1 ? "" : "s"} · <span className="mono">{p.project_id}</span></div>
          </button>
        </div>
        {kids.length > 0 && isOpen(p.project_id) && kids.map((r) => runItem(r, 1))}
      </div>
    );
  };

  return (
    <div className="card">
      <div className="hist-head">
        <h2>Run History</h2>
        {groups.length > 0 && (
          <span className="buttons tight">
            <button className="link" onClick={() => setOpen(new Set(groups))}>Expand all</button>
            <button className="link" onClick={() => setOpen(new Set())}>Collapse all</button>
          </span>
        )}
      </div>
      {runs.length === 0 && projects.length === 0 ? (
        <div className="muted small">No projects or runs yet.</div>
      ) : (
        <div className="history">
          {projects.map(projectItem)}
          {projects.length > 0 && otherRoots.length > 0 && <div className="muted small hist-sep">Other runs</div>}
          {otherRoots.map((r) => runItem(r, 0))}
        </div>
      )}
    </div>
  );
}
