import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { Schedule } from "../types";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function SchedulesPanel() {
  const [items, setItems] = useState<Schedule[]>([]);
  const [goal, setGoal] = useState("");
  const [mode, setMode] = useState("tiered");
  const [cadence, setCadence] = useState("weekly");
  const [weekday, setWeekday] = useState(0);

  const refresh = useCallback(async () => {
    try {
      setItems(await api.schedules());
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const add = async () => {
    if (goal.trim().length < 5) return;
    await api.addSchedule(goal.trim(), mode, cadence, weekday);
    setGoal("");
    await refresh();
  };

  return (
    <div className="panel">
      <h2>Scheduled goals</h2>
      <div className="composer">
        <textarea
          value={goal}
          placeholder="recurring goal — e.g. 'summarize new AI security papers and rate their relevance'"
          onChange={(e) => setGoal(e.target.value)}
        />
        <div className="composer-row">
          <select value={cadence} onChange={(e) => setCadence(e.target.value)}>
            <option value="daily">daily</option>
            <option value="weekly">weekly on</option>
          </select>
          {cadence === "weekly" && (
            <select value={weekday} onChange={(e) => setWeekday(Number(e.target.value))}>
              {WEEKDAYS.map((d, i) => (
                <option key={d} value={i}>{d}</option>
              ))}
            </select>
          )}
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="approve">approve</option>
            <option value="tiered">tiered</option>
            <option value="auto">auto</option>
          </select>
          <button onClick={() => void add()} disabled={goal.trim().length < 5}>schedule</button>
        </div>
      </div>
      <ul className="sched-list">
        {items.length === 0 && (
          <li className="empty">No recurring goals yet — perfect for weekly literature sweeps.</li>
        )}
        {items.map((s) => (
          <li key={s.id} className={`sched-item ${s.enabled ? "" : "disabled"}`}>
            <div className="sched-goal">{s.goal}</div>
            <div className="sched-meta">
              <span className="pill kind">{s.cadence}{s.cadence === "weekly" ? ` · ${WEEKDAYS[s.weekday]}` : ""}</span>
              <span className="pill">{s.mode}</span>
              <span className="stat">last: {s.last_run ? s.last_run.slice(5, 16).replace("T", " ") : "never"}</span>
              <span style={{ flex: 1 }} />
              <button className="ghost" onClick={() => void api.toggleSchedule(s.id).then(refresh)}>
                {s.enabled ? "pause" : "resume"}
              </button>
              <button className="bad ghost" onClick={() => void api.deleteSchedule(s.id).then(refresh)}>×</button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
