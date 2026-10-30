import { useEffect, useRef, useState } from "react";
import { ApiError, approveZoneCap, getProject, runProject, setProjectInputs } from "../api";
import { decisionClass, fmtTime, locationName, projectStatusClass } from "../format";
import type { Meta, Project, ProjectInputsPayload, ProjectLocation, StartFieldName, StartFields } from "../types";
import ServiceErrorBadge from "./ServiceErrorBadge";

// ---- start fields: typed by the SME, never filled in (D-59) -----------------------------------------------------
/** The text typed in the four start-field cells of one row. "" = nothing typed. This is the only starting state. */
export interface Draft { road_type: string; posted_speed_mph: string; traffic_volume: string; lane_closure: string }
export const EMPTY_DRAFT: Draft = { road_type: "", posted_speed_mph: "", traffic_volume: "", lane_closure: "" };
export const FIELDS: StartFieldName[] = ["road_type", "posted_speed_mph", "traffic_volume", "lane_closure"];
const FIELD_LABEL: Record<StartFieldName, string> = {
  road_type: "road type", posted_speed_mph: "speed", traffic_volume: "traffic volume", lane_closure: "lane closure",
};
const WHOLE_NUMBER = /^[1-9]\d*$/;  // a positive whole number, no upper limit

/** Cells showing values the SME already saved on the project. Not a default: an untouched project shows empty cells. */
export function toDraft(sf: Partial<StartFields> | undefined): Draft {
  return {
    road_type: sf?.road_type ?? "",
    posted_speed_mph: sf?.posted_speed_mph == null ? "" : String(sf.posted_speed_mph),
    traffic_volume: sf?.traffic_volume ?? "",
    lane_closure: sf?.lane_closure == null ? "" : sf.lane_closure ? "yes" : "no",
  };
}

/** What is sent: null for every empty (or invalid) cell. */
export function toFields(d: Draft): StartFields {
  const speed = d.posted_speed_mph.trim();
  return {
    road_type: d.road_type || null,
    posted_speed_mph: WHOLE_NUMBER.test(speed) ? Number(speed) : null,
    traffic_volume: d.traffic_volume || null,
    lane_closure: d.lane_closure === "" ? null : d.lane_closure === "yes",
  };
}

export const isRunnable = (l: ProjectLocation) => l.reject_reasons.length === 0 && l.geometry?.type === "POINT";

/** For each location that would run, the start fields still empty: its own cell, else the project row, else missing. */
export function missingByLocation(locations: ProjectLocation[], proj: Draft, over: Record<string, Draft>): Record<string, StartFieldName[]> {
  const all = toFields(proj);
  const out: Record<string, StartFieldName[]> = {};
  for (const l of locations.filter(isRunnable)) {
    const mine = toFields(over[l.location_id] ?? EMPTY_DRAFT);
    const miss = FIELDS.filter((f) => (mine[f] ?? all[f]) === null);
    if (miss.length) out[l.location_id] = miss;
  }
  return out;
}

const SELECT_HINT = "— select —";

interface CellsProps {
  draft: Draft; set: (d: Draft) => void; meta: Meta; who: string; inherit?: Draft;
}

/** The four start-field inputs of one row. In a point row an empty cell uses the project row's value (shown as a hint). */
function StartCells({ draft, set, meta, who, inherit }: CellsProps) {
  const hint = (f: StartFieldName, shown?: string) => (inherit && inherit[f] !== "" ? `project: ${shown ?? inherit[f]}` : SELECT_HINT);
  const speedBad = draft.posted_speed_mph.trim() !== "" && !WHOLE_NUMBER.test(draft.posted_speed_mph.trim());
  return (
    <>
      <td>
        <select aria-label={`${who} road type`} value={draft.road_type} onChange={(e) => set({ ...draft, road_type: e.target.value })}>
          <option value="">{hint("road_type")}</option>
          {meta.road_types.map((rt) => (
            <option key={rt} value={rt}>{rt}{meta.supported_road_types.includes(rt) ? "" : " (not in POC scope)"}</option>
          ))}
        </select>
      </td>
      <td>
        <input aria-label={`${who} speed`} inputMode="numeric" size={5} value={draft.posted_speed_mph} aria-invalid={speedBad}
               placeholder={inherit && inherit.posted_speed_mph !== "" ? `project: ${inherit.posted_speed_mph}` : "mph"}
               onChange={(e) => set({ ...draft, posted_speed_mph: e.target.value })} />
        {speedBad && <div className="small err">whole number above 0</div>}
      </td>
      <td>
        <select aria-label={`${who} traffic volume`} value={draft.traffic_volume} onChange={(e) => set({ ...draft, traffic_volume: e.target.value })}>
          <option value="">{hint("traffic_volume")}</option>
          {meta.traffic_volumes.map((v) => <option key={v} value={v}>{v === "HIGH" ? "High" : "Low"}</option>)}
        </select>
      </td>
      <td>
        <select aria-label={`${who} lane closure`} value={draft.lane_closure} onChange={(e) => set({ ...draft, lane_closure: e.target.value })}>
          <option value="">{hint("lane_closure", inherit?.lane_closure === "yes" ? "Yes" : "No")}</option>
          <option value="yes">Yes</option>
          <option value="no">No</option>
        </select>
      </td>
    </>
  );
}

// ---- the project view ---------------------------------------------------------------------------------------------
interface Props {
  projectId: string;
  meta: Meta;
  onOpenRun: (runId: string) => void;
  onChanged: () => void;  // the project list and run history are stale: reload them
}

const message = (e: unknown) => (e instanceof ApiError || e instanceof Error ? e.message : String(e));

export default function ProjectView({ projectId, meta, onOpenRun, onChanged }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [proj, setProj] = useState<Draft>(EMPTY_DRAFT);
  const [over, setOver] = useState<Record<string, Draft>>({});
  const [ta, setTa] = useState("AUTO");
  const [taOver, setTaOver] = useState<Record<string, string>>({});
  const [approver, setApprover] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialised = useRef(false);

  // First load: show what the SME already saved. Later polls update the status and runs, never the typed cells.
  useEffect(() => {
    let live = true;
    getProject(projectId).then((p) => {
      if (!live) return;
      setProject(p);
      if (!initialised.current) {
        initialised.current = true;
        setProj(toDraft(p.start_fields.project));
        setOver(Object.fromEntries(Object.entries(p.start_fields.per_location).map(([id, sf]) => [id, toDraft(sf)])));
        setTa(p.ta_hypothesis.project || "AUTO");
        setTaOver({ ...p.ta_hypothesis.per_location });
      }
    }).catch((e) => live && setError(message(e)));
    return () => { live = false; };
  }, [projectId]);

  const status = project?.status;
  useEffect(() => {
    if (status !== "RUNNING") return;
    const t = window.setInterval(() => { getProject(projectId).then(setProject).catch(() => undefined); onChanged(); }, 2000);
    return () => window.clearInterval(t);
  }, [status, projectId, onChanged]);

  if (!project) return <div className="card">{error ? <div className="banner bad small">{error}</div> : "Loading project…"}</div>;

  const usable = project.locations.filter((l) => l.reject_reasons.length === 0);
  const runnable = project.locations.filter(isRunnable);
  const missing = missingByLocation(project.locations, proj, over);
  const missingCount = Object.keys(missing).length;
  const name = (l: ProjectLocation) => locationName(project, l);
  const byId = new Map(project.locations.map((l) => [l.location_id, l]));
  const locked = busy || status === "RUNNING" || status === "ZONE_CAP_APPROVAL_REQUIRED";

  const inputsPayload = (): ProjectInputsPayload => ({
    project: toFields(proj),
    per_location: Object.fromEntries(usable.map((l) => [l.location_id, toFields(over[l.location_id] ?? EMPTY_DRAFT)])),
    ta_project: ta,
    ta_per_location: Object.fromEntries(usable.map((l) => [l.location_id, taOver[l.location_id] || null])),
  });

  async function act(fn: () => Promise<Project>) {
    setBusy(true); setError(null);
    try { setProject(await fn()); onChanged(); } catch (e) { setError(message(e)); } finally { setBusy(false); }
  }
  const run = () => act(async () => { await setProjectInputs(projectId, inputsPayload()); return runProject(projectId); });
  const save = () => act(() => setProjectInputs(projectId, inputsPayload()));
  const applyToAll = () => act(async () => {
    const p = await setProjectInputs(projectId, { project: toFields(proj), apply_to_all: true });
    setOver((prev) => Object.fromEntries(Object.entries(prev).map(([id, d]) => [id, {
      ...d, ...Object.fromEntries(FIELDS.filter((f) => proj[f] !== "").map((f) => [f, ""])),
    }])));  // the per-point cells of the fields just applied are cleared, as on the server
    return p;
  });
  const approve = () => act(() => approveZoneCap(projectId, approver.trim()));

  const nRunnable = project.zones.filter((z) => z.status !== "NOT_SUPPORTED_UNTIL_S14").length;
  const why = missingCount > 0
    ? `Run is disabled: ${missingCount} location${missingCount > 1 ? "s" : ""} still need${missingCount > 1 ? "" : "s"} ` +
      `${[...new Set(Object.values(missing).flat())].map((f) => FIELD_LABEL[f]).join(", ")}.`
    : null;
  const latest = project.inputs[project.inputs.length - 1];

  return (
    <>
      <div className="card">
        <div className="runhead">
          <h2>Project <span className="mono small">{project.project_id}</span></h2>
          <span className={`pill ${projectStatusClass(project.status)}`} data-testid="project-status">{project.status}</span>
          <span className="spacer" />
          <span className="muted small">{project.name} · {project.source.kind.toLowerCase()} · created {fmtTime(project.created_at)}</span>
        </div>
        {latest && (
          <div className="muted small">
            {project.inputs.length} upload{project.inputs.length > 1 ? "s" : ""}; labels follow the latest ({latest.sha256.slice(0, 8)}…,
            {" "}{fmtTime(latest.uploaded_at)}). Labels are names for the list and the sheet only; nothing is decided from them.
          </div>
        )}
        {error && <div className="banner bad small" role="alert">{error}</div>}
      </div>

      {status === "ZONE_CAP_APPROVAL_REQUIRED" && (
        <div className="banner warn" role="alert" data-testid="cap-banner">
          <div className="big">ZONE_CAP_APPROVAL_REQUIRED</div>
          <div>{nRunnable} zones, the limit is {project.max_zones}. Nothing runs until you approve.</div>
          <div className="optrow2">
            <input aria-label="Approved by" placeholder="Approved by (optional, not verified)" value={approver}
                   onChange={(e) => setApprover(e.target.value)} />
            <button className="primary inline" onClick={approve} disabled={busy}>Approve and run</button>
          </div>
        </div>
      )}
      {project.cap_approval && (
        <div className="muted small">Zone limit approved for {project.cap_approval.zone_count} zones by {project.cap_approval.approved_by}{" "}
          ({project.cap_approval.verified ? "verified" : "not verified"}), {fmtTime(project.cap_approval.approved_at)}.</div>
      )}

      <div className="card">
        <h2>Start fields</h2>
        <div className="muted small">Typed by you for every location before Run. Nothing here is filled in, calculated or defaulted.
          A point's own cell wins over the project row.</div>
        <table className="grid startgrid">
          <thead>
            <tr><th>Location</th><th>Road type</th><th>Speed (mph)</th><th>Traffic volume</th><th>Lane closure</th><th>Select TA</th></tr>
          </thead>
          <tbody>
            <tr className="projrow">
              <th scope="row">All points (project)</th>
              <StartCells draft={proj} set={setProj} meta={meta} who="project" />
              <td>
                <select aria-label="project Select TA" value={ta} onChange={(e) => setTa(e.target.value)}>
                  {meta.ta_choices.map((t) => <option key={t} value={t}>{t === "AUTO" ? "Auto" : t}</option>)}
                </select>
              </td>
            </tr>
            <tr>
              <td colSpan={6}>
                <button type="button" className="btn" onClick={applyToAll} disabled={locked}>Apply to all points</button>
                <span className="muted small"> clears the points' own cells for the fields typed above</span>
              </td>
            </tr>
            {usable.map((l) => {
              const who = name(l);
              const lat = l.geometry?.type === "POINT" ? (l.geometry.coords as number[]) : null;
              return (
                <tr key={l.location_id} data-testid="location-row">
                  <th scope="row">
                    <div>{who}</div>
                    <div className="muted small">
                      {l.geometry?.type.toLowerCase()}{lat ? ` · ${lat[0].toFixed(5)}, ${lat[1].toFixed(5)}` : ""}
                    </div>
                    {!isRunnable(l) && <div className="small warnText">zone does not run until S14 (lines and polygons)</div>}
                  </th>
                  {isRunnable(l) ? (
                    <>
                      <StartCells draft={over[l.location_id] ?? EMPTY_DRAFT} inherit={proj} meta={meta} who={who}
                                  set={(d) => setOver({ ...over, [l.location_id]: d })} />
                      <td>
                        <select aria-label={`${who} Select TA`} value={taOver[l.location_id] ?? ""}
                                onChange={(e) => setTaOver({ ...taOver, [l.location_id]: e.target.value })}>
                          <option value="">project: {ta === "AUTO" ? "Auto" : ta}</option>
                          {meta.ta_choices.map((t) => <option key={t} value={t}>{t === "AUTO" ? "Auto" : t}</option>)}
                        </select>
                      </td>
                    </>
                  ) : <td colSpan={5} className="muted small">no start fields needed</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
        <div className="muted small">Select TA is a hypothesis only: it is recorded and checked against the site facts from S7 on.</div>

        {project.locations.some((l) => l.reject_reasons.length > 0) && (
          <div className="banner info small" data-testid="rejected">
            <b>Not used</b>
            <ul className="reasons">
              {project.locations.filter((l) => l.reject_reasons.length > 0).map((l) => (
                <li key={l.location_id}>{name(l)}: {l.reject_reasons.map((c) => <span key={c} className="code">{c}</span>)}</li>
              ))}
            </ul>
          </div>
        )}

        <div className="runbar">
          <button className="primary inline" onClick={run} disabled={locked || missingCount > 0 || runnable.length === 0}
                  aria-describedby={why ? "run-why" : undefined}>
            {status === "RUNNING" ? "Running…" : busy ? "Working…" : "RUN PROJECT"}
          </button>
          <button className="btn" onClick={save} disabled={locked}>Save start fields</button>
          {why && <span id="run-why" className="muted small">{why}</span>}
        </div>
      </div>

      {project.zones.length > 0 && (
        <div className="card">
          <h2>Zones</h2>
          <table className="grid">
            <thead><tr><th>Zone</th><th>Location</th><th>Select TA</th><th>Run</th><th>Decision</th><th>Draft</th></tr></thead>
            <tbody>
              {project.zones.map((z) => {
                const zr = z.current_run_id ? project.zone_runs[z.current_run_id] : undefined;
                const loc = byId.get(z.location_ids[0]);
                return (
                  <tr key={z.zone_id} data-testid="zone-row">
                    <td><span className="mono small">{z.zone_id}</span> v{z.version}</td>
                    <td>{loc ? name(loc) : "—"}</td>
                    <td>{z.ta.value === "AUTO" ? "Auto" : z.ta.value}</td>
                    <td>
                      {z.current_run_id
                        ? <button className="link" onClick={() => onOpenRun(z.current_run_id!)}>{z.current_run_id}</button>
                        : z.status === "NOT_SUPPORTED_UNTIL_S14" ? <span className="muted small">no run (S14)</span>
                        : <span className="muted small">not started</span>}
                    </td>
                    <td>
                      {zr ? (
                        <>
                          <span className={`pill ${zr.state === "FINISHED" ? decisionClass(zr.decision) : "run"}`}>
                            {zr.state === "FINISHED" ? zr.decision ?? "FINISHED" : zr.state}
                          </span>{" "}
                          <ServiceErrorBadge codes={zr.service_error} />
                        </>
                      ) : "—"}
                    </td>
                    <td>{zr?.state === "FINISHED" ? (zr.draft_available ? "available" : "none") : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
