import { useState } from "react";
import { fileUrl, getText } from "../api";
import { fmtBytes } from "../format";

const INLINE = [".json", ".txt"];

interface Props {
  runId: string;
  name: string;
  size?: number;
}

/** One file the pipeline wrote. JSON/text can be viewed inline; everything opens or downloads as-is. */
export default function ArtifactLink({ runId, name, size }: Props) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inline = INLINE.some((ext) => name.toLowerCase().endsWith(ext));

  async function toggle() {
    if (!open && text === null) {
      try {
        const raw = await getText(fileUrl(runId, name));
        let shown = raw;
        if (name.toLowerCase().endsWith(".json")) {
          try {
            shown = JSON.stringify(JSON.parse(raw), null, 2);
          } catch {
            /* show as stored */
          }
        }
        setText(shown);
      } catch (e) {
        setError((e as Error).message);
      }
    }
    setOpen(!open);
  }

  return (
    <div className="artifact">
      <div className="artifact-row">
        <span className="mono small">{name}</span>
        {size !== undefined && <span className="muted small">{fmtBytes(size)}</span>}
        <span className="spacer" />
        {inline && (
          <button type="button" className="link" onClick={toggle}>
            {open ? "hide" : "view"}
          </button>
        )}
        <a className="link" href={fileUrl(runId, name)} target="_blank" rel="noreferrer">
          open
        </a>
        <a className="link" href={fileUrl(runId, name, true)}>
          download
        </a>
      </div>
      {open && (
        <pre className="viewer">{error ? `Could not load: ${error}` : text ?? "Loading…"}</pre>
      )}
    </div>
  );
}
