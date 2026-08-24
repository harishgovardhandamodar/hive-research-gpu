import { useState } from "react";
import { api } from "../api";
import type { AutonomyMode, Plan, Step } from "../types";

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

  return (
    <div className={`plan-card ${statusClass}`}>
      <div className="plan-head" onClick={() => setOpen(!open)}>
        <span className={`chev ${open ? "up" : ""}`}>›</span>
        <span className="plan-goal">{plan.goal}</span>
        <span className="pill">{plan.planner}</span>
        <span className="pill">{plan.status}</span>
      </div>
      {open && (
        <>
          <ol className="steps">
            {plan.steps.map((s) => (
              <li key={s.index} className={`step step-${s.state}`}>
                <span className="step-icon">{STATE_ICON[s.state]}</span>
                <div>
                  <code>{s.tool}</code>
                  {s.rationale && <p>{s.rationale}</p>}
                  {Object.keys(s.args).length > 0 && (
                    <pre className="args">{JSON.stringify(s.args)}</pre>
                  )}
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
