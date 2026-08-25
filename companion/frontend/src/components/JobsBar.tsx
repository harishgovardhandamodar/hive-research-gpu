import { usePulse } from "../hooks/usePulse";

export function JobsBar() {
  const { snap } = usePulse();
  const scanAgo = snap.last_scan
    ? Math.max(1, Math.round((Date.now() - new Date(snap.last_scan).getTime()) / 60000))
    : null;

  return (
    <footer className="jobsbar">
      <div className="jb-group">
        <span className={snap.hive_ok ? "dot ok" : "dot bad"}>hive</span>
        <span className="jb-item" title="goals currently executing">
          ▶ {snap.plans_running} plans
        </span>
        {snap.approvals_pending > 0 && (
          <span className="jb-item jb-warn" title="mutations waiting for your decision">
            ⏸ {snap.approvals_pending} approval{snap.approvals_pending > 1 ? "s" : ""}
          </span>
        )}
        <span className="jb-item" title="open proactive suggestions">
          ◆ {snap.suggestions_open} suggestions
        </span>
      </div>
      <div className="jb-group jb-center">
        {snap.fox_jobs.map((j) => (
          <span key={j.id} className="jb-job" title={`survey ${j.id} — ${j.stage} (${Math.round((j.progress ?? 0) * 100)}%)`}>
            📝 survey · {j.stage || j.status} · {Math.round((j.progress ?? 0) * 100)}%
          </span>
        ))}
        {snap.hive_jobs.map((j, i) => (
          <span key={i} className="jb-job" title={j.label}>
            ⚙ {String(j.label).slice(0, 40)}
          </span>
        ))}
        {snap.fox_jobs.length === 0 && snap.hive_jobs.length === 0 && (
          <span className="jb-idle">no background jobs</span>
        )}
      </div>
      <div className="jb-group">
        <span className="stat" title="episodic memory records">{snap.episodes} episodes</span>
        <span className="stat" title="last proactive signal scan">
          scanned {scanAgo !== null ? `${scanAgo}m ago` : "—"}
        </span>
      </div>
    </footer>
  );
}
