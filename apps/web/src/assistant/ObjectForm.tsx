import { useState } from "react";
import * as A from "./api";
import type { Json } from "./types";

const CLASSES = ["APPROVED_CATALOG_DEVICE", "UNAPPROVED_KNOWN_DEVICE", "SME_DEFINED_OBJECT", "PERSONNEL_POSITION", "GEOMETRY_ZONE"];
const CATS = ["SIGN", "PCMS", "CONE", "CHANNELIZING_DEVICE", "TAPER", "BUFFER", "FLAGGER", "PERSONNEL", "OTHER"];

// Typed proposed objects (closed schema). Anything outside the approved TA-1 catalog is an SME exception.
export default function ObjectForm({ cid, objects, initialId, onStaged }: { cid: string; objects: Json[]; initialId?: string; onStaged: (r: Json) => void }) {
  const [f, setF] = useState<Json>({ object_id: initialId ?? "", approval_class: "UNAPPROVED_KNOWN_DEVICE", category: "PCMS",
    sign_code: "W20-1", approach: "INCREASING_STATION", station_m: "", end_station_m: "", side: "RIGHT", offset_from_centerline_m: "",
    purpose: "", reason: "", confirm_unsupported: false });
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const approved = f.approval_class === "APPROVED_CATALOG_DEVICE";
  const zone = ["TAPER", "BUFFER"].includes(f.category) || f.approval_class === "GEOMETRY_ZONE";
  const submit = async () => {
    setErr(null);
    const num = (v: string) => (v === "" ? undefined : parseFloat(v));
    try {
      onStaged(await A.post<Json>(`conversations/${cid}/objects`, { ...f, station_m: num(f.station_m), end_station_m: zone ? num(f.end_station_m) : undefined,
        offset_from_centerline_m: num(f.offset_from_centerline_m), sign_code: approved ? f.sign_code : undefined }));
    } catch (e) { setErr((e as Error).message); }
  };
  const remove = async (oid: string) => {
    const reason = window.prompt(`Reason for removing ${oid}?`);
    if (!reason) return;
    try { onStaged(await A.post<Json>(`conversations/${cid}/objects/remove`, { object_id: oid, reason })); } catch (e) { setErr((e as Error).message); }
  };
  return (
    <details className="sme-details" open={!!initialId}><summary>Propose a new TCP object (e.g. create S3) / remove a device</summary>
      <div className="sme-choices">
        <input className="sme-input" placeholder="new id (e.g. S3)" value={f.object_id} onChange={set("object_id")} />
        <select value={f.approval_class} onChange={set("approval_class")}>{CLASSES.map((x) => <option key={x}>{x}</option>)}</select>
        <select value={f.category} onChange={set("category")}>{CATS.map((x) => <option key={x}>{x}</option>)}</select>
        {approved && <select value={f.sign_code} onChange={set("sign_code")}><option>W20-1</option><option>SHOULDER_WORK</option></select>}
        {(approved || f.category === "SIGN") && <select value={f.approach} onChange={set("approach")}><option>INCREASING_STATION</option><option>DECREASING_STATION</option></select>}
        <input className="sme-input" placeholder="station m" value={f.station_m} onChange={set("station_m")} />
        {zone && <input className="sme-input" placeholder="end station m" value={f.end_station_m} onChange={set("end_station_m")} />}
        <select value={f.side} onChange={set("side")}><option>LEFT</option><option>RIGHT</option></select>
        <input className="sme-input" placeholder="offset m (default roadside)" value={f.offset_from_centerline_m} onChange={set("offset_from_centerline_m")} />
        <input className="sme-input wide" placeholder="purpose (required)" value={f.purpose} onChange={set("purpose")} />
        <input className="sme-input wide" placeholder="reason (required)" value={f.reason} onChange={set("reason")} />
        {!approved && <label className="small"><input type="checkbox" checked={f.confirm_unsupported}
          onChange={(e) => setF({ ...f, confirm_unsupported: e.target.checked })} /> I confirm this object is UNSUPPORTED by the approved TA-1
          catalog and is a plan-specific engineering exception (not rule validated).</label>}
        <button className="btn small" onClick={submit}>Stage proposed object</button>
      </div>
      <div className="small">Remove an existing device:{" "}
        {objects.filter((o) => o.object_type !== "WORK_LOCATION").map((o) => (
          <button key={o.object_id} className="btn small" onClick={() => remove(o.object_id)}>Remove {o.object_id}</button>))}
      </div>
      {err && <div className="banner bad small">{err}</div>}
    </details>
  );
}
