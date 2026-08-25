import { useEffect, useState } from "react";
import type { AutonomyMode } from "../types";
import { AutonomySelect } from "./ui";
import { api } from "../api";
import { toast } from "../lib/toast";
import type { PlanTemplate } from "../types";

const MODE_HELP: Record<AutonomyMode, string> = {
  approve: "Every mutating step waits for your approval.",
  tiered: "Reads run automatically; mutations wait for approval.",
  auto: "Whole plan runs unattended once submitted.",
};

export function GoalComposer({
  onCreate,
  modes,
}: {
  onCreate: (goal: string, mode: AutonomyMode) => Promise<void>;
  modes: string[];
}) {
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState<AutonomyMode>("tiered");
  const [busy, setBusy] = useState(false);
  const [templates, setTemplates] = useState<PlanTemplate[]>([]);

  useEffect(() => {
    api
      .planTemplates()
      .then(setTemplates)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    const onPrefill = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      if (text) setGoal(text);
    };
    window.addEventListener("fox-prefill", onPrefill);
    return () => window.removeEventListener("fox-prefill", onPrefill);
  }, []);

  const submit = async () => {
    if (goal.trim().length < 3 || busy) return;
    setBusy(true);
    try {
      await onCreate(goal.trim(), mode);
      setGoal("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="composer">
      {templates.length > 0 && (
        <select
          value=""
          onChange={(e) => {
            const tpl = templates.find((t) => t.id === e.target.value);
            if (tpl) {
              setGoal(tpl.goal);
              toast(`template loaded: ${tpl.goal.slice(0, 40)} (${tpl.uses} uses)`);
            }
            e.target.value = "";
          }}
          aria-label="load a saved workflow template"
          title="re-run a saved successful workflow"
        >
          <option value="" disabled>
            ▸ saved workflows ({templates.length})
          </option>
          {templates.map((t) => (
            <option key={t.id} value={t.id}>
              {t.goal.slice(0, 46)} · ×{t.uses}
            </option>
          ))}
        </select>
      )}
      <textarea
        value={goal}
        placeholder="What should the companion do? e.g. 'survey recent work on graph neural networks' or 'improve notes I rated poorly'"
        onChange={(e) => setGoal(e.target.value)}
        disabled={busy}
        aria-busy={busy}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void submit();
        }}
      />
      <div className="composer-row">
        <AutonomySelect value={mode} onChange={(m) => setMode(m as AutonomyMode)} modes={modes} label="autonomy" />
        <button
          onClick={() => void submit()}
          disabled={busy || goal.trim().length < 3}
          title={goal.trim().length < 3 ? "describe the goal (at least 3 characters)" : undefined}
          className={busy ? "btn-busy" : ""}
        >
          {busy ? (
            <>
              <span className="spinner" aria-hidden /> planning…
            </>
          ) : (
            "set goal"
          )}
        </button>
      </div>
      <p className="hint">{goal.trim().length > 0 && goal.trim().length < 3 ? "keep typing — goals need at least 3 characters" : MODE_HELP[mode]}</p>
    </div>
  );
}
