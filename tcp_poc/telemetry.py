"""Lightweight, OpenTelemetry-compatible span hooks.

If `opentelemetry-api` is installed, spans are also emitted through the global tracer (configure an
exporter yourself; nothing paid is required). Without it, spans are recorded in memory and written to
run_report.txt. Attributes are filtered: never put keys, coordinates, KML payloads, images, prompts or
completions into span attributes - pass identifiers, versions, statuses, reason codes and bands only.
"""
import contextlib, os, time

try:  # optional dependency
    from opentelemetry import trace as _otel_trace
except Exception:  # pragma: no cover - absence is the normal POC case
    _otel_trace = None

SPAN_NAMES = ("tcp.input.parse", "tcp.map.retrieve", "tcp.osm.resolve", "tcp.vision.analyze", "tcp.site.fuse",
              "tcp.site.eligibility", "tcp.rulepack.load", "tcp.rules.execute", "tcp.geometry.place",
              "tcp.plan.validate", "tcp.debug.render", "tcp.dwt.render",
              "tcp.agent.call1", "tcp.agent.compare", "tcp.agent.crops", "tcp.agent.call2", "tcp.agent.consistency")

_BLOCKED_ATTR_FRAGMENTS = ("key", "token", "secret", "lat", "lon", "coord", "kml", "image", "prompt",
                           "completion", "password")


def _safe_attrs(attrs):
    out = {}
    for k, v in (attrs or {}).items():
        lk = k.lower()
        if any(b in lk for b in _BLOCKED_ATTR_FRAGMENTS): continue
        if isinstance(v, (list, tuple)): v = ",".join(str(x) for x in v)
        if isinstance(v, (str, int, float, bool)) or v is None: out[k] = v
    return out


def confidence_band(value):
    if value is None: return "NONE"
    return "HIGH" if value >= 0.85 else "MEDIUM" if value >= 0.6 else "LOW"


class Telemetry:
    def __init__(self, service="tcp-poc"):
        self.spans = []
        self._tracer = _otel_trace.get_tracer(service) if _otel_trace else None
        self._echo = os.environ.get("TCP_TELEMETRY_CONSOLE") == "1"

    @contextlib.contextmanager
    def span(self, name, **attrs):
        rec = {"name": name, "status": "OK", "attributes": _safe_attrs(attrs)}
        started = time.perf_counter()
        otel_cm = self._tracer.start_as_current_span(name) if self._tracer else contextlib.nullcontext()
        with otel_cm as otel_span:
            try:
                yield rec
            except Exception as e:
                rec["status"] = "ERROR"; rec["attributes"]["error.code"] = getattr(e, "code", type(e).__name__)
                raise
            finally:
                rec["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
                rec["attributes"] = _safe_attrs(rec["attributes"])
                if otel_span is not None:
                    for k, v in rec["attributes"].items():
                        if v is not None: otel_span.set_attribute(k, v)
                    otel_span.set_attribute("tcp.status", rec["status"])
                self.spans.append(rec)
                if self._echo:
                    print(f"   [span] {name} {rec['status']} {rec['duration_ms']}ms {rec['attributes']}", flush=True)

    def set(self, rec, **attrs):
        rec["attributes"].update(_safe_attrs(attrs))

    def summary_lines(self):
        lines = []
        for s in self.spans:
            attrs = " ".join(f"{k}={v}" for k, v in sorted(s["attributes"].items()))
            lines.append(f"  {s['name']:<22} {s['status']:<8} {s['duration_ms']:>9.1f} ms  {attrs}")
        return lines
