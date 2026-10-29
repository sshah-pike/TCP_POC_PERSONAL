import { useState, type FormEvent } from "react";
import { ApiError, createProject } from "../api";
import { fmtBytes } from "../format";
import type { InputType, LocationRow, Meta, NewProjectPayload } from "../types";

interface Props {
  meta: Meta;
  onCreated: (projectId: string) => void;
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

/** Why a KML gave no project: the file itself, or every location with its rejection reasons (NO_USABLE_LOCATION). */
export function Rejection({ error }: { error: ApiError }) {
  const rows: LocationRow[] = error.body.locations ?? [];
  const fileReasons = error.body.file_reasons ?? [];
  return (
    <div className="banner bad small" role="alert" data-testid="no-usable-location">
      <div className="big">No usable work location</div>
      <div>{error.message}. No project was created.</div>
      {fileReasons.length > 0 && <div>File rejected: {fileReasons.map((c) => <span key={c} className="code">{c}</span>)}</div>}
      {rows.length > 0 && (
        <ul className="reasons">
          {rows.map((l) => (
            <li key={l.location_id}>
              <b>{l.label || `Location ${l.ordinal + 1}`}</b>{l.type ? ` (${l.type.toLowerCase()})` : ""}:{" "}
              {l.reject_reasons.map((c) => <span key={c} className="code">{c}</span>)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** New project: one KML, one point or an offline scenario. The four start fields are NOT here: they are typed on the
 *  project, per location, and nothing fills them in. */
export default function NewProjectForm({ meta, onCreated }: Props) {
  const [inputType, setInputType] = useState<InputType>("kml");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [scenario, setScenario] = useState(meta.offline_scenarios[0] ?? "");
  const [mapProvider, setMapProvider] = useState("");
  const [aiProvider, setAiProvider] = useState("");
  const [dwtMode, setDwtMode] = useState("");
  const [noDwt, setNoDwt] = useState(false);
  const [aiProfile, setAiProfile] = useState("");
  const [evidenceMode, setEvidenceMode] = useState("single");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [open, setOpen] = useState(false);  // minimized by default

  const offline = inputType === "offline";
  const canCreate =
    !busy &&
    ((inputType === "kml" && file !== null) ||
      (inputType === "coordinates" && lat.trim() !== "" && lon.trim() !== "") ||
      (offline && scenario !== ""));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canCreate) return;
    setBusy(true);
    setError(null);
    try {
      const payload: NewProjectPayload = {
        input_type: inputType,
        advanced: { map_provider: mapProvider, ai_provider: aiProvider, dwt_mode: dwtMode, no_dwt: noDwt,
                    ai_profile: offline ? "" : aiProfile, evidence_mode: evidenceMode },
      };
      if (inputType === "kml" && file) payload.kml = { filename: file.name, content_base64: await readBase64(file) };
      if (inputType === "coordinates") Object.assign(payload, { lat: lat.trim(), lon: lon.trim() });
      if (offline) payload.offline_scenario = scenario;
      const project = await createProject(payload);
      onCreated(project.project_id);
    } catch (err) {
      setError(err as Error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={`card newrun ${open ? "" : "collapsed"}`} onSubmit={submit} aria-label="New project">
      <button type="button" className="newrun-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="twisty-icon">{open ? "▾" : "▸"}</span> New Project
        {!open && <span className="muted small">click to add a KML</span>}
      </button>

      <div className="field">
        <label className="label">Input type</label>
        <div className="radios">
          {([["kml", "KML"], ["coordinates", "Coordinates"], ["offline", "Offline self-test"]] as [InputType, string][]).map(([v, l]) => (
            <label key={v}>
              <input type="radio" checked={inputType === v} onChange={() => setInputType(v)} /> {l}
            </label>
          ))}
        </div>
      </div>

      {inputType === "kml" && (
        <div className={`dropzone ${dragOver ? "over" : ""}`}
             onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
             onDragLeave={() => setDragOver(false)}
             onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); }}>
          <input type="file" accept=".kml" aria-label="KML file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="muted small">Drop a .kml file here or choose one. Every Point becomes a zone with its own run.</div>
          {file && <div className="small"><b>{file.name}</b> · {fmtBytes(file.size)}</div>}
        </div>
      )}

      {inputType === "coordinates" && (
        <div className="row2">
          <div className="field">
            <label className="label">Latitude</label>
            <input type="text" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} />
          </div>
          <div className="field">
            <label className="label">Longitude</label>
            <input type="text" inputMode="decimal" value={lon} onChange={(e) => setLon(e.target.value)} />
          </div>
        </div>
      )}

      {offline && (
        <div className="field">
          <label className="label">Scenario</label>
          <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
            {meta.offline_scenarios.map((s) => <option key={s}>{s}</option>)}
          </select>
          <div className="muted small">Simulated road, imagery, OSM and AI observation – not real data.</div>
        </div>
      )}

      <div className="muted small">Road type, speed, traffic volume and lane closure are typed on the project, per location, before Run.</div>

      <details className="advanced">
        <summary>Advanced options</summary>
        {offline ? (
          <div className="muted small">Map and AI providers are fixed by the offline scenario.</div>
        ) : (
          <>
            <div className="row2">
              <div className="field">
                <label className="label">AI model profile (Foundry)</label>
                <select value={aiProfile} onChange={(e) => setAiProfile(e.target.value)}>
                  <option value="">(environment default)</option>
                  {meta.foundry_profiles.filter((p) => p.available).map((p) => (
                    <option key={p.name} value={p.name}>{p.display_name} ({p.deployment})</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label className="label">AI evidence</label>
                <select value={evidenceMode} onChange={(e) => setEvidenceMode(e.target.value)}>
                  <option value="single">single-resolution (overview only)</option>
                  <option value="multi">multi-resolution (overview + 3 close views)</option>
                </select>
              </div>
            </div>
            <div className="row2">
              <div className="field">
                <label className="label">Map provider</label>
                <select value={mapProvider} onChange={(e) => setMapProvider(e.target.value)}>
                  <option value="">(environment default)</option>
                  {meta.map_providers.map((p) => <option key={p}>{p}</option>)}
                </select>
              </div>
              <div className="field">
                <label className="label">AI provider</label>
                <select value={aiProvider} onChange={(e) => setAiProvider(e.target.value)}>
                  <option value="">(environment default)</option>
                  {meta.ai_providers.map((p) => <option key={p}>{p}</option>)}
                </select>
              </div>
            </div>
          </>
        )}
        <div className="row2">
          <div className="field">
            <label className="label">DWT mode</label>
            <select value={dwtMode} disabled={noDwt} onChange={(e) => setDwtMode(e.target.value)}>
              <option value="">(default: PLAN)</option>
              {meta.dwt_modes.map((m) => <option key={m}>{m}</option>)}
            </select>
          </div>
          <div className="field">
            <label className="label">&nbsp;</label>
            <label><input type="checkbox" checked={noDwt} onChange={(e) => setNoDwt(e.target.checked)} /> Skip DWT renderer</label>
          </div>
        </div>
      </details>

      {error instanceof ApiError && error.code === "NO_USABLE_LOCATION"
        ? <Rejection error={error} />
        : error && <div className="banner bad small">{error.message}</div>}
      <button className="primary" type="submit" disabled={!canCreate}>{busy ? "Creating…" : "CREATE PROJECT"}</button>
    </form>
  );
}
