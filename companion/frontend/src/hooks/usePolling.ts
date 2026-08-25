import { useEffect, useRef } from "react";

/**
 * Interval polling with cleanup and error isolation. Replaces the
 * setInterval/clearInterval boilerplate previously hand-rolled in every panel.
 * The interval keeps running even if one fetch fails — fn is expected to
 * catch its own errors (or pass onError to surface them).
 */
export function usePolling(fn: () => void | Promise<void>, ms: number) {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    void ref.current();
    const t = setInterval(() => void ref.current(), ms);
    return () => clearInterval(t);
  }, [ms]);
}
