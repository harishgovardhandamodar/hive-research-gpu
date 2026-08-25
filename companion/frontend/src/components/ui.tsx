import type { ReactNode } from "react";

/** Inline error with optional retry — the one true way to show a failure. */
export function ErrorNote({
  message,
  onRetry,
  children,
}: {
  message: string;
  onRetry?: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="banner error" role="alert">
      <span>{message}</span>
      {onRetry && (
        <button className="ghost" onClick={onRetry}>
          retry
        </button>
      )}
      {children}
    </div>
  );
}

/** Consistent empty/loading placeholder for panels. */
export function EmptyState({
  hint,
  skeleton,
  as = "p",
}: {
  hint?: string;
  skeleton?: boolean;
  as?: "p" | "li" | "div";
}) {
  const Tag = as;
  if (skeleton) {
    return (
      <Tag className="empty">
        <span className="skeleton-stack" aria-busy="true" aria-label="loading">
          {[0, 1, 2].map((i) => (
            <i key={i} className="skeleton-row" />
          ))}
        </span>
      </Tag>
    );
  }
  return <Tag className="empty">{hint}</Tag>;
}

export function Pill({ kind, title, children }: { kind?: string; title?: string; children: ReactNode }) {
  return (
    <span className={`pill ${kind ?? ""}`} title={title}>
      {children}
    </span>
  );
}

/** Tool arguments as readable key/value chips instead of a raw JSON dump. */
export function ArgsView({ args }: { args: Record<string, unknown> }) {
  const entries = Object.entries(args);
  if (entries.length === 0) return null;
  return (
    <span className="args-chips">
      {entries.map(([k, v]) => (
        <code key={k} className="arg-chip" title={`${k}: ${String(v)}`}>
          {k}={String(v).slice(0, 40)}
          {String(v).length > 40 ? "…" : ""}
        </code>
      ))}
    </span>
  );
}
