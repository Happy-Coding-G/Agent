import { useEffect, useRef } from "react";

export default function Splitter(props: {
  axis: "x" | "y";
  onDrag: (delta: number) => void;
  ariaLabel?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const dragging = useRef(false);
  const last = useRef<number>(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const onDown = (e: MouseEvent) => {
      dragging.current = true;
      last.current = props.axis === "x" ? e.clientX : e.clientY;
      e.preventDefault();
    };
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const cur = props.axis === "x" ? e.clientX : e.clientY;
      const delta = cur - last.current;
      last.current = cur;
      props.onDrag(delta);
      e.preventDefault();
    };
    const onUp = () => {
      dragging.current = false;
    };

    el.addEventListener("mousedown", onDown);
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      el.removeEventListener("mousedown", onDown);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [props]);

  return (
    <div
      ref={ref}
      className="splitter"
      role="separator"
      aria-label={props.ariaLabel ?? "Splitter"}
      style={props.axis === "x" ? { width: 6 } : { height: 6, width: "100%", cursor: "row-resize" }}
    />
  );
}
