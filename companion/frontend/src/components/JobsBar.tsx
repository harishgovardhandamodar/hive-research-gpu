import { usePulse } from "../hooks/usePulse";
import { timeAgo } from "../lib/time";

export function JobsBar() {
  const { snap } = usePulse();
  const scanAgo = timeAgo(snap.last_scan);

  const hasPlans = snap.plan_progress.length > 0;

  return (
    <footer className="jobsbar">
      <div className="jb-group">
        <span className={snap.hive_ok ? "dot ok" : "dot bad"}>hive</span>
        <span className="jb-item" title="goals currently executing">
          <span className={hasPlans ? "spinner spinner-sm" : ""} aria-hidden style={{ display: hasPlans ? "inline-block" : "none" }} /> ▶ {snap.plans_running} plans
        </span>
        {snap.approvals_pending > 0 && (
          <span className="jb-item jb-warn" title="mutations waiting for your decision">
            ⏸ {snap.approvals_pending} approval{snap.approvals_pending > 1 ? "s" : ""}
          </span>
        )}
        <span className="jb-item" title="open proactive suggestions">
          ◆ {snap.suggestions_open} suggestions
        </span>
        {snap.ingest_failures > 0 && (
          <a href="#discover" className="jb-item jb-warn" title="failed ingestions — see Discover to rerun">
            ✖ {snap.ingest_failures} failed
          </a>
        )}
      </div>
      <div className="jb-group jb-center">
        {hasPlans ? (
          <>
            {snap.plan_progress.map((p) => (
              <span key={p.id} className="jb-job jb-plan" title={`${p.goal} — ${p.done}/${p.total} · ${p.current_tool} (${p.current_state})`}>
                <span className="jb-plan-goal">{p.goal.slice(0, 36)}</span>
                <span className="jb-progress">
                  <span className="jb-progress-fill" style={{ width: `${Math.round(p.progress * 100)}%` }} />
                </span>
                <span className="jb-plan-meta">
                  {p.done}/{p.total} · {p.current_tool || "queued"}
                </span>
              </span>
            ))}
          </>
        ) : (
          <>
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
            {snap.fox_jobs.length === 0 && snap.hive_jobs.length === 0 && <span className="jb-idle">no background jobs</span>}
          </>
        )}
      </div>
      <div className="jb-group">
        <span className="stat" title="episodic memory records">{snap.episodes} episodes</span>
        <span className="stat" title="last proactive signal scan">
          scanned {scanAgo}
        </span>
      </div>
    </footer>
  );
}
