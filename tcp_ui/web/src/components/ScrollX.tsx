import { useEffect, useRef, useState, type ReactNode } from "react";

/** Horizontally scrollable box whose scrollbar floats at the bottom of the window while the box is on screen,
 *  so wide tables can be scrolled left/right without first scrolling down to their end. */
export default function ScrollX({ className, children }: { className?: string; children: ReactNode }) {
  const body = useRef<HTMLDivElement>(null);
  const bar = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  const [overflow, setOverflow] = useState(false);

  useEffect(() => {
    const el = body.current;
    if (!el) return;
    const measure = () => { setWidth(el.scrollWidth); setOverflow(el.scrollWidth > el.clientWidth + 1); };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    for (const c of Array.from(el.children)) ro.observe(c);
    return () => ro.disconnect();
  }, [children]);

  // Two-way sync; the guard stops each programmatic update from echoing back.
  const syncing = useRef(false);
  const sync = (from: HTMLDivElement | null, to: HTMLDivElement | null) => {
    if (!from || !to) return;
    if (syncing.current) { syncing.current = false; return; }
    if (to.scrollLeft !== from.scrollLeft) { syncing.current = true; to.scrollLeft = from.scrollLeft; }
  };

  return (
    <div className={className}>
      <div ref={body} className="scroll-x-body" onScroll={() => sync(body.current, bar.current)}>{children}</div>
      {overflow && (
        <div ref={bar} className="scroll-x-bar" onScroll={() => sync(bar.current, body.current)}>
          <div style={{ width, height: 1 }} />
        </div>
      )}
    </div>
  );
}
