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

const AUTONOMY_HELP: Record<string, string> = {
  approve: "Every mutating step waits for your approval.",
  tiered: "Reads run automatically; mutations wait for approval.",
  auto: "Whole plan runs unattended once submitted.",
};

/** The one true autonomy-mode dropdown — previously duplicated in four panels. */
export function AutonomySelect({
  value,
  onChange,
  modes,
  label,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  modes: string[];
  label?: string;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      disabled={disabled}
      title={AUTONOMY_HELP[value] ?? "autonomy mode"}
      aria-label={label ?? "autonomy mode"}
      onChange={(e) => onChange(e.target.value)}
    >
      {modes.map((m) => (
        <option key={m} value={m}>
          {label ? `${label}: ${m}` : m}
        </option>
      ))}
    </select>
  );
}
