import { fileUrl } from "../api";
import type { RunState } from "../types";

/** Viewer for the artifacts the existing renderers produced. Draws nothing itself. */
export default function FinalDraft({ run }: { run: RunState }) {
  const has = (n: string) => run.outputs.some((o) => o.name === n);
  const url = (n: string) => fileUrl(run.run_id, n);
  const buttons: [string, string, boolean][] = [
    ["View TCP Sheet PDF", "tcp_sheet.pdf", false],
    ["View TCP Sheet PNG", "tcp_sheet.png", false],
    ["View Debug Plan (PNG)", "debug_plan.png", false],
    ["View Debug Plan (PDF)", "debug_plan.pdf", false],
    ["View Plan JSON", "plan.json", false],
    ["Download DXF", "plan.dxf", true],
    ["Download DWG", "plan.dwg", true],
    ["View Run Report", "run_report.txt", false],
  ];
  const sheet = run.stages.find((s) => s.key === "render")?.spans.find((s) => s.name === "tcp.sheet.render");
  const dwt = run.dwt;

  return (
    <div className="card">
      <h2>FINAL TCP DRAFT</h2>
      <div className="muted small">
        Plan <span className="mono">{run.plan.plan_id}</span> · hash <span className="mono">{run.plan.plan_hash}</span>
        <br />
        Produced by the existing pipeline renderers. AUTOMATED DRAFT – NOT APPROVED FOR FIELD USE.
      </div>
      <div className="buttons">
        {buttons
          .filter(([, n]) => has(n))
          .map(([label, n, dl]) =>
            dl ? (
              <a key={n} className="btn" href={fileUrl(run.run_id, n, true)}>
                {label}
              </a>
            ) : (
              <a key={n} className="btn" href={url(n)} target="_blank" rel="noreferrer">
                {label}
              </a>
            ),
          )}
      </div>

      {has("tcp_sheet.png") ? (
        <a href={url("tcp_sheet.png")} target="_blank" rel="noreferrer">
          <img className="preview" src={url("tcp_sheet.png")} alt="tcp_sheet.png (existing engineering sheet)" />
        </a>
      ) : has("tcp_sheet.pdf") ? (
        <iframe className="pdf" src={url("tcp_sheet.pdf")} title="tcp_sheet.pdf" />
      ) : (
        <>
          <div className="banner warn small">
            The engineering sheet (tcp_sheet) was not produced in this run
            {sheet ? ` (tcp.sheet.render status_code=${String(sheet.attributes["status_code"] ?? "—")})` : ""}. The image
            below is the pipeline's <b>debug plan</b>, not the authoritative engineering sheet.
          </div>
          {has("debug_plan.png") && (
            <a href={url("debug_plan.png")} target="_blank" rel="noreferrer">
              <img className="preview" src={url("debug_plan.png")} alt="debug_plan.png (debug view)" />
            </a>
          )}
        </>
      )}

      <h3>DWT / CAD output</h3>
      {!dwt ? (
        <div className="muted small">No DWT result recorded.</div>
      ) : dwt.status === "RENDERED" ? (
        <div className="small">
          RENDERED ({dwt.mode}) – {(dwt.outputs ?? []).join(", ")}
        </div>
      ) : dwt.status === "SKIPPED" ? (
        <div className="muted small">DWT renderer skipped for this run.</div>
      ) : (
        <div className="banner warn small">
          <b className="mono">{dwt.error_code}</b> – {dwt.message}
          {dwt.details !== undefined && <pre className="viewer short">{JSON.stringify(dwt.details, null, 2)}</pre>}
        </div>
      )}
    </div>
  );
}
