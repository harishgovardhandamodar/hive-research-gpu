import { useEffect, useState } from "react";
import type { AutonomyMode } from "../types";

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
        <select value={mode} onChange={(e) => setMode(e.target.value as AutonomyMode)} title={MODE_HELP[mode]}>
          {modes.map((m) => (
            <option key={m} value={m}>
              autonomy: {m}
            </option>
          ))}
        </select>
        <button onClick={() => void submit()} disabled={busy} className={busy ? "btn-busy" : ""}>
          {busy ? (
            <>
              <span className="spinner" aria-hidden /> planning…
            </>
          ) : (
            "set goal"
          )}
        </button>
      </div>
      <p className="hint">{MODE_HELP[mode]}</p>
    </div>
  );
}
