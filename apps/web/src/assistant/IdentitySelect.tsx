import { useEffect, useState } from "react";
import * as A from "./api";
import type { IdentityList, WhoAmI } from "./types";

// Local POC identity selection (no login page, no credentials). Authorization is enforced by the backend.
export default function IdentitySelect({ onChange }: { onChange: (me: WhoAmI | null) => void }) {
  const [list, setList] = useState<IdentityList | null>(null);
  const [me, setMe] = useState<WhoAmI | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    A.identities().then(setList).catch((e: Error) => setErr(e.message));
    if (A.getToken()) A.whoami().then((m) => { setMe(m); onChange(m); }).catch(() => { A.setToken(null); onChange(null); });
  }, [onChange]);

  const choose = async (sid: string) => {
    setErr(null);
    try {
      if (me) await A.endSession();
      if (!sid) { setMe(null); onChange(null); return; }
      await A.selectIdentity(sid);
      const m = await A.whoami(); setMe(m); onChange(m);
    } catch (e) { setErr((e as Error).message); }
  };

  if (!list) return err ? <span className="muted small">SME identity: {err}</span> : null;
  return (
    <label className="small identity-select">
      SME identity{" "}
      <select value={me?.identity.subject_id ?? ""} onChange={(e) => choose(e.target.value)}>
        <option value="">— select —</option>
        {list.identities.map((i) => (
          <option key={i.subject_id} value={i.subject_id}>{i.display_name} ({i.roles.join(", ")})</option>
        ))}
      </select>
      {!list.configured && <span className="muted"> {list.note}</span>}
      {err && <span className="bad-text"> {err}</span>}
    </label>
  );
}
