/** A service/API failure (imagery, OSM or AI) among a run's reason codes. It sits next to the decision and never replaces it:
 *  exit code 3 is REVIEW_REQUIRED whether or not a service call failed. */
export default function ServiceErrorBadge({ codes }: { codes?: string[] | boolean | null }) {
  if (!codes) return null;
  const list = Array.isArray(codes) ? codes : [];
  return (
    <span className="pill warn badge" title={list.length ? `Service problem: ${list.join(", ")}` : "A service call failed"}
          data-testid="service-error">
      service error
    </span>
  );
}
