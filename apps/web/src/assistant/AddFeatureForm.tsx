import { useState } from "react";
import type { Json } from "./types";

const KINDS = ["intersections", "driveways", "crosswalks", "roundabouts", "ramps", "obstructions"];

// Structured form: add a missing site feature (deterministic; no AI).
export default function AddFeatureForm({ onSubmit }: { onSubmit: (p: Json) => void }) {
  const [kind, setKind] = useState("driveways");
  const [station, setStation] = useState("");
  const [side, setSide] = useState("RIGHT");
  const [desc, setDesc] = useState("");
  const [reason, setReason] = useState("");
  return (
    <details className="sme-details"><summary>Add a missing site feature</summary>
      <div className="sme-choices">
        <select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k}>{k}</option>)}</select>
        <input className="sme-input" placeholder="station m" value={station} onChange={(e) => setStation(e.target.value)} />
        <select value={side} onChange={(e) => setSide(e.target.value)}><option>LEFT</option><option>RIGHT</option><option>BOTH</option><option>UNKNOWN</option></select>
        <input className="sme-input" placeholder="description" value={desc} onChange={(e) => setDesc(e.target.value)} />
        <input className="sme-input wide" placeholder="reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className="btn small" onClick={() => onSubmit({ kind, station_m: parseFloat(station), side, description: desc, reason })}>Stage feature</button>
      </div>
    </details>
  );
}
