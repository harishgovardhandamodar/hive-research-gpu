import { useState } from "react";
import { api } from "../api";
import type { AutonomyMode, Plan, Step } from "../types";
import { ArgsView } from "./ui";

const STATE_ICON: Record<Step["state"], string> = {
  pending: "·",
  awaiting_approval: "⏸",
  running: "▶",
  done: "✓",
  skipped: "⤼",
  failed: "✗",
};

export function PlanCard({ plan, onModeSwitch }: { plan: Plan; onModeSwitch: () => void }) {
  const [open, setOpen] = useState(true);
  const [mode, setMode] = useState<AutonomyMode>("tiered");

  const switchMode = async (next: AutonomyMode) => {
    setMode(next);
    try {
      await api.switchMode(plan.id, next);
    } catch {
      /* plan may have finished */
    }
    onModeSwitch();
  };

  const statusClass = ["failed", "done", "running"].includes(plan.status) ? `plan-${plan.status}` : "";
  const total = plan.steps.length;
  const done = plan.steps.filter((s) => ["done", "failed", "skipped"].includes(s.state)).length;
  const runningIdx = plan.steps.findIndex((s) => s.state === "running" || s.state === "awaiting_approval");
  const progress = total ? done / total : 0;

  return (
    <div className={`plan-card ${statusClass}`}>
      {total > 0 && (
        <div className="plan-progress" title={`${done}/${total} steps`}>
          <div className="plan-progress-fill" style={{ width: `${Math.round(progress * 100)}%` }} />
        </div>
      )}
      <div
        className="plan-head"
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen(!open);
          }
        }}
      >
        <span className={`chev ${open ? "up" : ""}`}>›</span>
        <span className="plan-goal">{plan.goal}</span>
        <span className="pill">{plan.planner}</span>
        <span className={`pill pill-status status-${plan.status}`}>{plan.status}</span>
        {plan.status === "running" && runningIdx >= 0 && (
          <span className="pill pill-running" title={`step ${runningIdx + 1}/${total}: ${plan.steps[runningIdx].tool}`}>
            <span className="spinner spinner-sm" aria-hidden /> {plan.steps[runningIdx].tool}
          </span>
        )}
      </div>
      {open && (
        <>
          <ol className="steps">
            {plan.steps.map((s) => (
              <li key={s.index} className={`step step-${s.state}`}>
                <span className="step-icon">
                  {s.state === "running" ? <span className="spinner spinner-sm" aria-hidden /> : STATE_ICON[s.state]}
                </span>
                <div>
                  <code>{s.tool}</code>
                  {s.rationale && <p>{s.rationale}</p>}
                  <ArgsView args={s.args} />
                </div>
              </li>
            ))}
          </ol>
          <div className="composer-row">
            <select value={mode} onChange={(e) => void switchMode(e.target.value as AutonomyMode)}>
              <option value="approve">switch: approve</option>
              <option value="tiered">switch: tiered</option>
              <option value="auto">switch: auto</option>
            </select>
          </div>
        </>
      )}
    </div>
  );
}
