import { useCallback, useEffect, useState } from "react";

export interface Toast {
  id: number;
  text: string;
  kind: "info" | "ok" | "error";
}

let nextId = 1;

/** Fire a transient notification from anywhere (no hooks needed). */
export function toast(text: string, kind: Toast["kind"] = "ok") {
  window.dispatchEvent(new CustomEvent("fox-toast", { detail: { text, kind } }));
}

export function Toaster() {
  const [items, setItems] = useState<Toast[]>([]);

  const push = useCallback((text: string, kind: Toast["kind"]) => {
    const id = nextId++;
    setItems((list) => [...list.slice(-3), { id, text, kind }]);
    setTimeout(() => setItems((list) => list.filter((t) => t.id !== id)), 3500);
  }, []);

  useEffect(() => {
    const onToast = (e: Event) => {
      const detail = (e as CustomEvent<{ text: string; kind?: Toast["kind"] }>).detail;
      if (detail?.text) push(detail.text, detail.kind ?? "ok");
    };
    window.addEventListener("fox-toast", onToast);
    return () => window.removeEventListener("fox-toast", onToast);
  }, [push]);

  if (items.length === 0) return null;
  return (
    <div className="toaster" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={`toast toast-${t.kind}`}>
          {t.text}
        </div>
      ))}
    </div>
  );
}
