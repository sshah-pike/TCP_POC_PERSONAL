import { useState, type FormEvent } from "react";
import { startRun } from "../api";
import { fmtBytes } from "../format";
import type { InputType, Meta, NewRunPayload } from "../types";

interface Props {
  meta: Meta;
  onStarted: (runId: string) => void;
}

function readBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

export default function NewRunForm({ meta, onStarted }: Props) {
  const [inputType, setInputType] = useState<InputType>("kml");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");
  const [scenario, setScenario] = useState(meta.offline_scenarios[0] ?? "");
  const [offlineInput, setOfflineInput] = useState("coordinates");
  const [roadType, setRoadType] = useState("");
  const [speed, setSpeed] = useState("");
  const [laneClosure, setLaneClosure] = useState(false);
  const [options, setOptions] = useState<{ key: string; value: string }[]>([]);
  const [mapProvider, setMapProvider] = useState("");
  const [aiProvider, setAiProvider] = useState("");
  const [dwtMode, setDwtMode] = useState("");
  const [noDwt, setNoDwt] = useState(false);
  const [aiProfile, setAiProfile] = useState("");
  const [evidenceMode, setEvidenceMode] = useState("single");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const offline = inputType === "offline";
  const canRun =
    !busy &&
    ((inputType === "kml" && file !== null) ||
      (inputType === "coordinates" && lat.trim() !== "" && lon.trim() !== "") ||
      (offline && scenario !== ""));

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!canRun) return;
    setBusy(true);
    setError(null);
    try {
      const payload: NewRunPayload = {
        input_type: inputType,
        operator: { road_type: roadType, speed, requires_lane_closure: laneClosure, options },
        advanced: { map_provider: mapProvider, ai_provider: aiProvider, dwt_mode: dwtMode, no_dwt: noDwt,
                    ai_profile: offline ? "" : aiProfile, evidence_mode: evidenceMode },
      };
      if (inputType === "kml" && file) payload.kml = { filename: file.name, content_base64: await readBase64(file) };
      if (inputType === "coordinates") Object.assign(payload, { lat: lat.trim(), lon: lon.trim() });
      if (offline) Object.assign(payload, { offline_scenario: scenario, offline_input: offlineInput });
      onStarted(await startRun(payload));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const setOpt = (i: number, k: "key" | "value", v: string) =>
    setOptions(options.map((o, j) => (j === i ? { ...o, [k]: v } : o)));

  const [open, setOpen] = useState(false);  // minimized by default
  return (
    <form className={`card newrun ${open ? "" : "collapsed"}`} onSubmit={submit}>
      <button type="button" className="newrun-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <span className="twisty-icon">{open ? "▾" : "▸"}</span> New Run
        {!open && <span className="muted small">click to start a run</span>}
      </button>

      <div className="field">
        <label className="label">Input type</label>
        <div className="radios">
          {(
            [
              ["kml", "KML"],
              ["coordinates", "Coordinates"],
              ["offline", "Offline self-test"],
            ] as [InputType, string][]
          ).map(([v, l]) => (
            <label key={v}>
              <input type="radio" checked={inputType === v} onChange={() => setInputType(v)} /> {l}
            </label>
          ))}
        </div>
      </div>

      {inputType === "kml" && (
        <div
          className={`dropzone ${dragOver ? "over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
          }}
        >
          <input type="file" accept=".kml" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <div className="muted small">Drop a .kml file here or choose one.</div>
          {file && (
            <div className="small">
              <b>{file.name}</b> · {fmtBytes(file.size)}
              <div className="muted">Saved under var/runs/&lt;run-id&gt;/input/ when the run starts.</div>
            </div>
          )}
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
        <div className="row2">
          <div className="field">
            <label className="label">Scenario</label>
            <select value={scenario} onChange={(e) => setScenario(e.target.value)}>
              {meta.offline_scenarios.map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="label">Offline input</label>
            <select value={offlineInput} onChange={(e) => setOfflineInput(e.target.value)}>
              <option value="coordinates">coordinates</option>
              <option value="kml">kml</option>
            </select>
          </div>
          <div className="muted small span2">Simulated road, imagery, OSM and AI observation – not real data.</div>
        </div>
      )}

      <h3>Operator parameters</h3>
      <div className="field">
        <label className="label">Road type (Table 6B-1) — operator-confirmed, never inferred</label>
        <select value={roadType} onChange={(e) => setRoadType(e.target.value)}>
          <option value="">{offline ? "(scenario default)" : "(not provided)"}</option>
          {meta.road_types.map((rt) => (
            <option key={rt} value={rt}>
              {rt}
              {meta.supported_road_types.includes(rt) ? "" : " (not in POC scope)"}
            </option>
          ))}
        </select>
        {!offline && roadType === "" && (
          <div className="muted small">Without a road type the pipeline stops with REVIEW_REQUIRED.</div>
        )}
      </div>
      <div className="row2">
        <div className="field">
          <label className="label">Speed, mph (informational)</label>
          <input type="number" step="1" value={speed} onChange={(e) => setSpeed(e.target.value)} />
        </div>
        <div className="field">
          <label className="label">&nbsp;</label>
          <label>
            <input type="checkbox" checked={laneClosure} onChange={(e) => setLaneClosure(e.target.checked)} />{" "}
            Requires lane closure
          </label>
        </div>
      </div>

      <details className="advanced">
        <summary>Advanced options</summary>
        <div className="field">
          <label className="label">TA-1 option facts (--option KEY=VALUE)</label>
          {options.map((o, i) => (
            <div className="optrow" key={i}>
              <input placeholder="key" value={o.key} onChange={(e) => setOpt(i, "key", e.target.value)} />
              <span>=</span>
              <input placeholder="value" value={o.value} onChange={(e) => setOpt(i, "value", e.target.value)} />
              <button type="button" className="link" onClick={() => setOptions(options.filter((_, j) => j !== i))}>
                remove
              </button>
            </div>
          ))}
          <button type="button" className="link" onClick={() => setOptions([...options, { key: "", value: "" }])}>
            + add option
          </button>
        </div>
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
                {meta.map_providers.map((p) => (
                  <option key={p}>{p}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label className="label">AI provider</label>
              <select value={aiProvider} onChange={(e) => setAiProvider(e.target.value)}>
                <option value="">(environment default)</option>
                {meta.ai_providers.map((p) => (
                  <option key={p}>{p}</option>
                ))}
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
              {meta.dwt_modes.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="label">&nbsp;</label>
            <label>
              <input type="checkbox" checked={noDwt} onChange={(e) => setNoDwt(e.target.checked)} /> Skip DWT renderer
              (--no-dwt)
            </label>
          </div>
        </div>
      </details>

      {error && <div className="banner bad small">{error}</div>}
      <button className="primary" type="submit" disabled={!canRun}>
        {busy ? "Starting…" : "RUN PIPELINE"}
      </button>
    </form>
  );
}
