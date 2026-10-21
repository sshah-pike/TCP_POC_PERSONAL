// Inline stroke icons (decorative: aria-hidden; every use is paired with visible text).
const P: Record<string, string> = {
  pipeline: "M4 6h16M4 12h10M4 18h6M18 14l3 3-3 3",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7 9a7 7 0 0 1 14 0",
  spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z",
  form: "M5 4h14v16H5zM8 9h8M8 13h8M8 17h5",
  calc: "M6 3h12v18H6zM9 7h6M9 11h1M12 11h1M15 11h0M9 15h1M12 15h1M15 15h0",
  alert: "M12 3l9.5 17h-19zM12 10v4M12 17.5v.5",
  review: "M4 5h16v14H4zM8 9h8M8 13h5M15 15l2 2 3-4",
  check: "M5 12.5l4.5 4.5L19 7",
  layers: "M12 3l9 5-9 5-9-5zM3 13l9 5 9-5",
  shield: "M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v6M12 7.5v.5",
  down: "M12 5v14M6 13l6 6 6-6",
  close: "M6 6l12 12M18 6L6 18",
  expand: "M4 10V4h6M20 14v6h-6M4 4l7 7M20 20l-7-7",
  collapse: "M10 4v6H4M14 20v-6h6M4 10l6-6M20 14l-6 6",
  chevron: "M9 6l6 6-6 6",
  issues: "M9 11l2 2 4-4M5 4h14v16H5z",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  ask: "M4 5h16v11H9l-5 4zM9 9h6M9 12h4",
  image: "M4 5h16v14H4zM4 15l4-4 4 4 3-3 5 5M15 9h.01",
  switch: "M7 7h13l-3-3M17 17H4l3 3",
  plus: "M12 5v14M5 12h14",
  back: "M15 6l-6 6 6 6",
  send: "M4 12l16-8-6 16-2.5-6.5zM11.5 13.5L20 4",
  trash: "M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13M10 11v6M14 11v6",
};

export function Icon({ name, size = 16 }: { name: string; size?: number }) {
  return (
    <svg className="sme-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
         strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={P[name] ?? P.info} />
    </svg>
  );
}

// Assistant mark: a traffic-sign diamond with an engineering check - used on the launcher and the panel header.
export function AssistantMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="smeg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#6366f1" /><stop offset="1" stopColor="#4338ca" /></linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="9" fill="url(#smeg)" />
      <path d="M16 6.5l9.5 9.5L16 25.5 6.5 16z" fill="#fbbf24" stroke="#1f2937" strokeWidth="1.2" />
      <path d="M12.2 16.2l2.6 2.6 5-5.3" fill="none" stroke="#1f2937" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
